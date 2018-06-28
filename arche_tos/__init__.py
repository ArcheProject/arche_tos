# -*- coding: utf-8 -*-
from translationstring import TranslationStringFactory


_ = TranslationStringFactory('arche_tos')


def includeme(config):
    config.include('.models')
    config.include('.resource')
    config.include('.schemas')
    config.include('.views')
