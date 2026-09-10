{
    "name": "POS · Cobro con cheque",
    "version": "19.0.5.2.0",
    "summary": "Cobrar con cheque en el punto de venta, con los datos del cheque",
    "description": """
Permite cobrar con cheque en el POS pidiendo los datos que hacen falta para que
el cheque quede REGISTRADO y no como un cobro genérico: número, banco, CUIT del
librador y fecha de cobro. Sin esos datos no deja validar la venta.

Es el mismo patrón que `yaguven_pos_tarjeta` usa para el cupón: los datos se
piden en la línea de pago, apenas el cajero elige el medio, y se validan también
del lado del servidor (la validación del navegador se puede saltear).

Sólo hereda de modelos NATIVOS de Odoo (C.2). Los datos viven en la línea de
pago del POS; ningún campo de dato se agrega a un modelo de un tercero.
""",
    "author": "Guvens Consultora",
    "website": "https://yaguven.com",
    "category": "Point of Sale",
    "license": "LGPL-3",
    # Sólo nativos. `l10n_latam_check` NO se declara como dependencia a
    # propósito: este módulo junta los DATOS del cheque, y quien los convierte
    # en un cheque en cartera es una pieza aparte. Así el POS sigue andando
    # aunque la localización cambie.
    "depends": ["point_of_sale"],
    "data": [
        "views/pos_payment_method_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "yaguven_pos_cheque/static/src/js/pos_payment.js",
            "yaguven_pos_cheque/static/src/js/payment_lines.js",
            "yaguven_pos_cheque/static/src/js/payment_screen.js",
            "yaguven_pos_cheque/static/src/xml/payment_screen.xml",
        ],
    },
    "installable": True,
    "application": False,
}
