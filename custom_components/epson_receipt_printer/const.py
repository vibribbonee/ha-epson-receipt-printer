"""Constants for the Epson ESC/POS integration."""

DOMAIN = "epson_receipt_printer"
CONF_NAME = "name"
CONF_HOST = "host"
CONF_PORT = "port"
DEFAULT_PORT = 9100
DEFAULT_TIMEOUT = 5.0

SERVICE_PRINT_TEXT = "print_text"
SERVICE_PRINT_SHOPPING_LIST = "print_shopping_list"

# mDNS service name; stays the same when the printer gets a new IP.
CONF_ZEROCONF_NAME = "zeroconf_name"
