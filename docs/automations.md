# Automatizaciones declarativas

TextPik carga flujos desde `~/.config/textpik/automations.json`. El motor no
ejecuta shell, limita cada flujo a 16 pasos y siempre muestra una vista previa
antes de reemplazar texto. El cambio completo puede deshacerse como una sola
operación.

```json
{
  "automations": [
    {
      "id": "clean-note",
      "name": "Limpiar nota",
      "icon": "remove-breaks.svg",
      "enabled": true,
      "conditions": {
        "application": "firefox",
        "text_types": ["text"],
        "min_length": 3,
        "max_length": 5000,
        "editable": true
      },
      "steps": [
        {"operation": "remove-breaks"},
        {"operation": "capitalize"},
        {"operation": "suffix", "value": "."}
      ]
    }
  ]
}
```

Operaciones admitidas: `uppercase`, `lowercase`, `capitalize`,
`remove-breaks`, `replace`, `prefix` y `suffix`. Las condiciones admiten
aplicación, tipo de texto, editabilidad, longitud y una expresión regular
limitada. Los proveedores externos se mantienen como acciones explícitas con
sus propios permisos y timeouts.
