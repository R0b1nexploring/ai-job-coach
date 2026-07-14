from datetime import datetime


def dump(row, exclude: set[str] | None = None) -> dict:
    exclude = exclude or set()
    result = {}
    for column in row.__table__.columns:
        if column.name in exclude:
            continue
        value = getattr(row, column.name)
        result[column.name] = value.isoformat() if isinstance(value, datetime) else value
    return result


def listed(items: list, page: int = 1, page_size: int = 20) -> dict:
    return {"items": items, "page": page, "page_size": page_size, "total": len(items)}

