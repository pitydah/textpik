# Automatizaciones declarativas

TextPik carga flujos desde `~/.config/textpik/automations.json`. El motor no
ejecuta shell, limita cada flujo a 16 pasos y siempre muestra una vista previa
antes de reemplazar texto. El cambio completo puede deshacerse como una sola
operación.

Los mismos flujos pueden crearse y editarse en **Configuración → Acciones →
Automatizaciones visuales**. El editor gráfico escribe este formato declarativo;
nunca crea ni ejecuta comandos de shell. Los pasos pueden reordenarse arrastrando
o con los controles de movimiento. Las plantillas incluidas se copian al flujo,
por lo que cada automatización puede modificarse de forma independiente.

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

Las expresiones regulares no admiten referencias hacia atrás, lookarounds ni
grupos con cuantificadores anidados. Cada resultado intermedio está limitado a
un millón de caracteres.
