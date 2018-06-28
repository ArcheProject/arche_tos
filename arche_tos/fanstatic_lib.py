# -*- coding: utf-8 -*-
from arche.fanstatic_lib import common_js
from fanstatic import Library, Resource


library = Library('arche_tos', 'static')

terms_modal = Resource(library, 'tos.js', depends=(common_js,))
