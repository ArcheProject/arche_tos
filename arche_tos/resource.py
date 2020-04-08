# -*- coding: utf-8 -*-
from arche.utils import utcnow
from zope.interface import implementer
from arche.resources import Content
from arche.resources import ContextACLMixin

from arche_tos.interfaces import ITOS
from arche_tos import _


@implementer(ITOS)
class TOS(Content, ContextACLMixin):
    type_name = "TOS"
    type_title = _("Terms of service")
    add_permission = 'Add TOS'
    nav_visible = False
    listing_visible = True
    search_visible = False
    title = ""
    body = ""
    collapse_text = False
    revoke_body = ""
    lang = ""
    date = None
    check_password_on_revoke = False
    check_typed_on_revoke = False

    @property
    def is_active(self):
        if self.wf_state == "enabled":
            today = utcnow().date()
            return self.date is not None and today >= self.date
        return False


def includeme(config):
    config.add_content_factory(TOS, addable_to='Folder')
    config.set_content_workflow('TOS', 'activate_workflow')
