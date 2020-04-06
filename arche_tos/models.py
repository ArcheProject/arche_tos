# -*- coding: utf-8 -*-
from datetime import timedelta
from logging import getLogger

from arche.interfaces import IBaseView
from arche.interfaces import IRoot
from arche.interfaces import IUser
from arche.interfaces import IViewInitializedEvent
from arche.security import PERM_MANAGE_SYSTEM
from arche.utils import AttributeAnnotations
from arche.utils import utcnow
from pyramid.decorator import reify
from pyramid.interfaces import IRequest
from repoze.catalog.query import Eq
from zope.component import adapter
from zope.interface import implementer

from arche_tos.events import ImportantAgreementsRevoked
from arche_tos.exceptions import TermsNeedAcceptance
from arche_tos.exceptions import TermsNotAccepted
from arche_tos.fanstatic_lib import terms_modal
from arche_tos.interfaces import IAgreedTOS
from arche_tos.interfaces import IRevokedTOS
from arche_tos.interfaces import ITOSManager
from arche_tos.interfaces import ITOSSettings

logger = getLogger(__name__)


@implementer(ITOSManager)
@adapter(IRequest)
class TOSManager(object):
    """ Checks for registered schemas with the type_name Terms.
        Any schema registered there must be agreed upon to be valid.

        Terms can also have versions.
    """

    grace_seconds = 60 * 10
    check_interval = 60 * 60
    logger = logger  # Testing injection

    def __init__(self, request):
        self.request = request

    def check_terms(self):
        if self.needs_check():
            # Skip check for admins
            if not self.request.has_permission(PERM_MANAGE_SYSTEM, self.request.root):
                # Find TOS that needs to be accepted
                for tos in self.find_tos():
                    if tos.uid not in self.agreed_tos:
                        self.logger.debug("Terms need acceptance: %s", tos)
                        self.check_grace_period()
                        raise TermsNeedAcceptance(
                            "TOS UID need acceptance: %s" % tos.uid
                        )
            self.mark_checked()

    def needs_check(self):
        try:
            return self.request.session["tos_check_again_at"] < utcnow()
        except KeyError:
            pass
        if self.agreed_tos is not None:
            return True

    def mark_checked(self):
        self.request.session["tos_check_again_at"] = utcnow() + timedelta(
            seconds=self.check_interval
        )
        self.request.session.changed()
        self.logger.debug("%s mark terms checked", self.request.authenticated_userid)

    def check_grace_period(self):
        sess = self.request.session
        if "tos_grace_period_expires" not in self.request.session:
            self.logger.debug(
                "%s started grace period of %s seconds",
                self.request.authenticated_userid,
                self.grace_seconds,
            )
            sess["tos_grace_period_expires"] = utcnow() + timedelta(
                seconds=self.grace_seconds
            )
        if utcnow() > sess["tos_grace_period_expires"]:
            raise TermsNotAccepted()

    def clear_grace_period(self):
        if "tos_grace_period_expires" in self.request.session:
            del self.request.session["tos_grace_period_expires"]
            self.request.session.changed()

    def clear_checked(self):
        if "tos_check_again_at" in self.request.session:
            del self.request.session["tos_check_again_at"]
            self.request.session.changed()

    def find_tos(self, filter_agreed=True):
        query = Eq("type_name", "TOS") & Eq("wf_state", "enabled")
        # The date query did not work as expected for me
        # Investigate this more! /rharms
        # Le('date', timegm(utcnow().date().timetuple()))
        docids = self.request.root.catalog.query(query)[1]
        today = utcnow().date()
        for tos in self.request.resolve_docids(docids, perm=None):
            # The language aspect
            if tos.lang and tos.lang != self.request.localizer.locale_name:
                continue
            if today >= tos.date:
                if filter_agreed:
                    if tos.uid not in self.agreed_tos:
                        yield tos
                else:
                    yield tos

    def agree_to(self, seq):
        for tos in seq:
            self.agreed_tos.accept_tos(tos.uid)
            if tos.uid in self.revoked_tos:
                del self.revoked_tos[tos.uid]
        self.clear_grace_period()

    def revoke_agreement(self, tos):
        active_tos = frozenset(self.find_tos(filter_agreed=False))
        important_revoked = []
        if tos.uid in self.agreed_tos:
            if tos in active_tos:
                important_revoked.append(tos)
                # No need to save revoke for inactive terms, so only here
                self.revoked_tos.revoke_tos(tos.uid)
            del self.agreed_tos[tos.uid]
        if important_revoked:
            self.send_revoked_event(important_revoked)
        return important_revoked

    @reify
    def agreed_tos(self):
        if self.request.profile:
            return IAgreedTOS(self.request.profile)

    @reify
    def revoked_tos(self):
        if self.request.profile:
            return IRevokedTOS(self.request.profile)

    def send_revoked_event(self, important_revoked):
        """ Fire an event when a user revokes their consent for a term that's important. """
        event = ImportantAgreementsRevoked(
            self.request.profile, important_revoked, self.request
        )
        self.request.registry.notify(event)

    def get_all_revoked_users(self, filter_tos_uids=None):
        """ A very slow and tedious call.
            Returns a generator that yields a user and a dict with uids as key and date revoked as value
        """
        if filter_tos_uids:
            filter_tos_uids = frozenset(filter_tos_uids)
        for user in self.request.root["users"].values():
            revoked_tos = IRevokedTOS(user)
            revoked_uids = frozenset(revoked_tos.keys())
            if revoked_uids:
                if filter_tos_uids:
                    relevant_revoked = filter_tos_uids & revoked_uids
                    if relevant_revoked:
                        yield user, dict(
                            [
                                (k, v)
                                for k, v in revoked_tos.items()
                                if k in relevant_revoked
                            ]
                        )
                else:
                    yield user, dict([(k, v) for k, v in revoked_tos.items()])

    def get_consent_managers(self):
        settings = ITOSSettings(self.request.root)
        users = self.request.root["users"]
        for userid in settings.get("data_consent_managers", ()):
            try:
                yield users[userid]
            except KeyError:
                logger.warning(
                    "Set data consent manager userid '%s' doesn't exist.", userid
                )

    def get_data_controller(self, default=""):
        settings = ITOSSettings(self.request.root)
        return settings.get("data_controller", default)


@adapter(IUser)
@implementer(IAgreedTOS)
class AgreedTOS(AttributeAnnotations):
    """ Handles a named storage for keys/values.
        UID of agreed terms will be key, and value will be a date.
    """

    attr_name = "_agreed_tos"

    def accept_tos(self, uid):
        self[uid] = utcnow().date()


@adapter(IUser)
@implementer(IRevokedTOS)
class RevokedTOS(AttributeAnnotations):
    """ Handles a named storage for keys/values.
        UID of revoked terms will be key, and value will be a date.
    """

    attr_name = "_revoked_tos"

    def revoke_tos(self, uid):
        self[uid] = utcnow().date()


@adapter(IRoot)
@implementer(ITOSSettings)
class TOSSettings(AttributeAnnotations):
    """ Handles a named storage for keys/values.
        Basically all settings from the TOSSettingsSchema.
    """

    attr_name = "_tos_settings"


def check_terms(view, event):
    request = view.request
    # Should not be used for xhr requests
    if request.is_xhr:
        return
    # Only show for authenticated
    if not request.authenticated_userid:
        return
    # Don't mix accept terms popups with other TOS functionality
    if getattr(request, "view_name", "") in (
        "tos_form",
        "revoke_agreement",
        "agreed_tos",
    ):
        return
    terms_manager = ITOSManager(request)
    try:
        # If the grace period expired, this will raise an uncaught TermsNotAccepted
        return terms_manager.check_terms()
    except TermsNeedAcceptance:
        terms_modal.need()
        return


def includeme(config):
    """
    Include components

    In your paster ini file, add the following keys to customize:
    # Number of seconds to wait before kicking out users that haven't agreed
    arche_tos.grace_seconds = <int>
    # Number of seconds to wait between each check
    arche_tos.check_interval = <int>
    """
    settings = config.registry.settings
    prefix = "arche_tos.%s"
    for k in ("grace_seconds", "check_interval"):
        key = prefix % k
        if key in settings:
            val = int(settings[key])
            setattr(TOSManager, k, val)
    config.registry.registerAdapter(TOSManager)
    config.registry.registerAdapter(AgreedTOS)
    config.registry.registerAdapter(RevokedTOS)
    config.registry.registerAdapter(TOSSettings)
    config.add_subscriber(check_terms, [IBaseView, IViewInitializedEvent])
