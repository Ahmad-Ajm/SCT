"""
Exporters package.

The initializer stays light so importing one exporter does not require every
optional output dependency (for example ``openpyxl`` for JSON-only workflows).
"""

__all__ = ["CSVExporter", "ExcelExporter", "JSONExporter", "XMLExporter"]


def __getattr__(name: str):
    if name == "CSVExporter":
        from exporters.csv_exporter import CSVExporter

        return CSVExporter
    if name == "ExcelExporter":
        from exporters.excel_exporter import ExcelExporter

        return ExcelExporter
    if name == "JSONExporter":
        from exporters.json_exporter import JSONExporter

        return JSONExporter
    if name == "XMLExporter":
        from exporters.xml_exporter import XMLExporter

        return XMLExporter
    raise AttributeError(f"module 'exporters' has no attribute {name!r}")
