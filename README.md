<img src="custom_components/epson_receipt_printer/brand/icon.png" alt="" width="64" height="64" align="right">

# Epson ESC/POS Receipt Printer

Turn Home Assistant lists and automations into paper receipts on a networked ESC/POS printer.

[![Add to Home Assistant Marketplace](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=vibribbonee&repository=ha-epson-receipt-printer&category=integration)

## Features

- Print a to-do list, formatted text, or receipt layouts.
- Add barcodes or QR codes, including store loyalty codes.
- Trigger printing from an automation or dashboard button over your local network.

## Install

Install from Home Assistant Marketplace and restart Home Assistant. Then go to **Settings → Devices & services → Add integration → Epson ESC/POS Receipt Printer**. Enter the printer’s address and port. Keep your existing entry when upgrading.

## Print a receipt

In Home Assistant, open **Developer Tools → Actions**, select **Epson ESC/POS Receipt Printer: Print text**, and choose your printer. The action can also run in an automation.

```yaml
action: epson_receipt_printer.print_text
data:
  config_entry_id: YOUR_PRINTER_CONFIG_ENTRY_ID
  text: "Shopping list: apples, milk, bread"
```

[Receipt and shopping-list printing options](custom_components/epson_receipt_printer/services.yaml)

## Contributing

Pull requests are welcome. Describe the change and how you tested it.

[MIT license](LICENSE). OpenAI Codex assisted with development, testing, and documentation.
