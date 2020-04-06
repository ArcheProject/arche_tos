from arche.interfaces import IUser
from pyramid.interfaces import IRequest
from zope.interface import implementer

from arche_tos.interfaces import IImportantAgreementsRevoked
from arche_tos.interfaces import ITOS


@implementer(IImportantAgreementsRevoked)
class ImportantAgreementsRevoked(object):
    """ When a user no longer consents to something that's still active. """

    def __init__(self, user, revoked_tos, request):
        # Static typing old style... :(
        assert IUser.providedBy(user)
        if ITOS.providedBy(revoked_tos):
            revoked_tos = [revoked_tos]
        else:
            for tos in revoked_tos:
                assert ITOS.providedBy(tos)
        assert IRequest.providedBy(request)
        self.user = user
        self.revoked_tos = revoked_tos
        self.request = request
