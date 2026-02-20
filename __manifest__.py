{
    'name': 'Customización en Flujo de Inventario',
    'summary': 'Permite capturar y guardar la distribución analítica por cada línea (producto) en las Entregas del módulo de Inventario.',
    'version': '1.0.0',
    'category': 'Technical',
    'description': 'Este módulo técnico extiende Inventario para añadir el campo “Distribución Analítica” por cada ítem (línea) en las Entregas (Delivery Orders). La analítica se registra directamente en la línea de movimiento (stock.move), permitiendo asignar centros de costo/analítica por producto dentro del mismo documento de entrega, sin depender del módulo de Manufactura.',
    'author': 'Telemática',
    'website': 'https://telematica.hn',
    'depends': [
        'stock', 'accountant', 'analytic', 'stock_account'
    ],
    'data': [
        'data/ir_sequence.xml',
        'security/ir.model.access.csv',
        "views/stock_picking_views.xml",
        "views/inventory_revaluation_views.xml",
        "views/inventory_revaluation_menu.xml",
    ],
    'license': 'OPL-1',
    'auto_install': False,
    'application': False,
    'installable': True,
    'maintainer': 'Telemática Development Team',
}