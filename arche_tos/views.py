# -*- coding: utf-8 -*-
import colander
import deform
from arche.interfaces import IFlashMessages
from arche.interfaces import IRoot
from arche.interfaces import IUser
from arche.security import PERM_EDIT
from arche.security import PERM_MANAGE_USERS
from arche.security import PERM_VIEW
from arche.views.actions import generic_submenu_items
from arche.views.base import BaseForm
from arche.views.base import BaseView
from arche.views.base import button_cancel
from pyramid.decorator import reify
from pyramid.httpexceptions import HTTPFound
from pyramid.httpexceptions import HTTPNotFound
from pyramid.renderers import render
from pyramid.response import Response
from pyramid.security import forget

from arche_tos import _
from arche_tos.exceptions import TermsNotAccepted
from arche_tos.interfaces import ITOS, ITOSSettings
from arche_tos.interfaces import ITOSManager


class TOSMixin(object):
    @reify
    def tos_manager(self):
        return ITOSManager(self.request)

    @reify
    def active_tos(self):
        return sorted(self.tos_manager.find_tos(), key=lambda x: x.title.lower())

    @reify
    def missing_settings(self):
        settings = ITOSSettings(self.request.root)
        schema = self.request.get_schema(self.request.root, 'TOS', 'settings')
        try:
            self.request.validate_appstruct(schema, dict(settings))
            return False
        except colander.Invalid:
            return True


class TOSForm(BaseForm, TOSMixin):
    type_name = "TOS"
    schema_name = "agree"
    title = _("New terms require your attention")
    buttons = (deform.Button("agree", title=_("Agree")),)

    @property
    def use_ajax(self):
        return self.request.is_xhr

    def before_fields(self):
        values = {"tos_items": self.tos_manager.find_tos(), "view": self}
        return render(
            "arche_tos:templates/tos_listing.pt", values, request=self.request
        )

    def agree_success(self, appstruct):
        self.flash_messages.add(_("Thank you!"), type="success")
        self.tos_manager.agree_to(self.tos_manager.find_tos())
        if self.use_ajax:
            return Response(
                render(
                    "arche:templates/deform/destroy_modal.pt", {}, request=self.request
                )
            )
        return HTTPFound(location=self.request.resource_url(self.context))


class AgreedTOSView(BaseView, TOSMixin):
    def __call__(self):
        active = []
        inactive = []
        for uid, date in self.tos_manager.agreed_tos.items():
            tos = self.request.resolve_uid(uid, perm=None)
            if tos:
                if tos.wf_state == "enabled":
                    active.append((tos, date))
                else:
                    inactive.append((tos, date))
        active = sorted(active, key=lambda x: x[1])
        inactive = sorted(inactive, key=lambda x: x[1])
        return {"active_tos": active, "inactive_tos": inactive}


class RevokeAgreementForm(BaseForm, TOSMixin):
    type_name = "TOS"
    schema_name = "revoke"
    title = _("Revoke agreement")

    @property
    def buttons(self):
        kwargs = {}
        if self.context.wf_state == "enabled":
            kwargs["css_class"] = "btn-danger"
        return (deform.Button("revoke", title=_("Revoke"), **kwargs), button_cancel)

    @reify
    def tos(self):
        uid = self.request.params.get("tos", None)
        if uid:
            # Current user probably hasn't got view permission on that object as default.
            # Which is correct, it shouldn't be part of the site.
            tos = self.request.resolve_uid(uid, perm=None)
            if not ITOS.providedBy(tos):
                raise HTTPNotFound(_("Agreement not found"))
            return tos

    def before_fields(self):
        # List the consequences of revoking this agreement
        values = {"tos": self.tos, "view": self}
        return render(
            "arche_tos:templates/revoke_tos_consequence.pt",
            values,
            request=self.request,
        )

    def revoke_success(self, appstruct):
        important_revoked = self.tos_manager.revoke_agreement(self.tos)
        if important_revoked:
            msg = _(
                "revoked_consent_enabled_tos",
                default="You've revoked your consent. "
                "Note that this website will not be usable without "
                "agreeing to these terms.",
            )
        else:
            msg = _(
                "revoked_consent_inactive_tos",
                default="You've revoked your consent to terms that were marked as inactive.",
            )
        self.tos_manager.clear_checked()
        self.flash_messages.add(
            msg, type="danger", require_commit=False, auto_destruct=False
        )
        return self.relocate_response(
            self.request.resource_url(self.profile, "agreed_tos")
        )

    def cancel_success(self, *args):
        return self.relocate_response(
            self.request.resource_url(self.profile, "agreed_tos")
        )

    cancel_failure = cancel_success


class ManageTOSView(BaseView, TOSMixin):
    def __call__(self):
        return {}


class ListRevokedUsers(BaseView, TOSMixin):
    def __call__(self):
        return {}

    @reify
    def revoke_nums(self):
        """ UID as key and a num starting with 1 as value. """
        return dict([(y, x) for x, y in enumerate([x.uid for x in self.active_tos], 1)])

    def get_revoked_users(self):
        uids = [x.uid for x in self.active_tos]
        return self.tos_manager.get_all_revoked_users(filter_tos_uids=uids)


class TOSSettings(BaseForm):
    schema_name = "settings"
    type_name = "TOS"

    @reify
    def settings(self):
        return ITOSSettings(self.context)

    def appstruct(self):
        return dict(self.settings)

    def _relocate_response(self):
        return HTTPFound(
            location=self.request.resource_url(self.context, "_manage_tos")
        )

    def save_success(self, appstruct):
        if appstruct != self.appstruct():
            self.settings.clear()
            self.settings.update(appstruct)
            self.flash_messages.add(self.default_success, type="success")
        else:
            self.flash_messages.add(_("No changes made"))
        return self._relocate_response()

    def cancel(self, *args):
        return self._relocate_response()

    cancel_failure = cancel_success = cancel


def terms_not_accepted(context, request):
    headers = forget(request)
    request.session.invalidate()
    fm = IFlashMessages(request)
    fm.add(
        _("You need to accept the terms to use this site."),
        type="danger",
        require_commit=False,
        auto_destruct=False,
    )
    # Context is the exception
    return HTTPFound(location=request.resource_url(request.root), headers=headers)


def agreed_tos_menu_item(context, request, va, **kw):
    """
    Render menu item in profile.
    """
    return """
    <li><a href="%s">%s</a></li>
    """ % (
        request.resource_url(request.profile, "agreed_tos"),
        request.localizer.translate(va.title),
    )


def includeme(config):
    config.add_view(
        TOSForm,
        context=IRoot,
        name="tos_form",
        permission=PERM_VIEW,
        renderer="arche:templates/form.pt",
    )
    config.add_view(
        AgreedTOSView,
        context=IUser,
        name="agreed_tos",
        permission=PERM_VIEW,
        renderer="arche_tos:templates/agreed_tos.pt",
    )
    config.add_view(
        RevokeAgreementForm,
        context=IUser,
        name="revoke_agreement",
        permission=PERM_EDIT,
        renderer="arche:templates/form.pt",
    )
    config.add_view(
        ManageTOSView,
        context=IRoot,
        name="_manage_tos",
        permission=PERM_MANAGE_USERS,
        renderer="arche_tos:templates/manage_tos.pt",
    )
    config.add_view(
        ListRevokedUsers,
        context=IRoot,
        name="_list_revoked_tos_users",
        permission=PERM_MANAGE_USERS,
        renderer="arche_tos:templates/list_revoked_users.pt",
    )
    config.add_view(
        TOSSettings,
        context=IRoot,
        name="_tos_settings",
        permission=PERM_MANAGE_USERS,
        renderer="arche:templates/form.pt",
    )
    config.add_exception_view(terms_not_accepted, context=TermsNotAccepted)
    config.add_view_action(
        agreed_tos_menu_item,
        "user_menu",
        "agreed_tos",
        title=_("Terms of service"),
        priority=40,
    )
    config.add_view_action(
        generic_submenu_items,
        "site_menu",
        "manage_tos",
        title=_("Manage TOS"),
        permission=PERM_MANAGE_USERS,
        priority=50,
        view_name="_manage_tos",
    )
