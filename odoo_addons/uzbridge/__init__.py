from . import controllers, models, wizard
from odoo.addons.payment import reset_payment_provider, setup_provider


def post_init_hook(env):
    setup_provider(env, 'uzbridge')
    uzs = env.ref('base.UZS', raise_if_not_found=False)
    if uzs and not uzs.active:
        uzs.active = True


def uninstall_hook(env):
    reset_payment_provider(env, 'uzbridge')
