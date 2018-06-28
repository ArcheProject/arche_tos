# -*- coding: utf-8 -*-

class TermsNeedAcceptance(Exception):
    """ Raised when new terms needs to be accepted. Will cause a modal window to appear.
    """


class TermsNotAccepted(Exception):
    """ Raised when terms haven't been accepted and the grace period has run out.
        Will cause the user to be logged out.
    """
