"""私有模块共用的严格数值、时间与错误边界。"""
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation


class LedgerError(ValueError):
    """可安全展示的固定业务错误，不包含输入原文或本机路径。"""


def now():
    """生成服务器实际收到记录的 UTC 时间。"""
    return datetime.now(timezone.utc).isoformat()


def stamp(value, optional=False):
    """只接受含时区的 ISO 时间，统一为 UTC 供截止日比较。"""
    if optional and value in (None, ''):
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError):
        raise LedgerError('时间必须为带时区的 ISO 日期时间。') from None


def day(value):
    """校验完整交易日期，不向日期添加执行时刻。"""
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise LedgerError('交易日期必须为 YYYY-MM-DD。') from None


def decimal(value, optional=False):
    """拒绝浮点、非有限和过大数值，以文本保存十进制精度。"""
    if optional and value in (None, ''):
        return None
    try:
        if isinstance(value, (float, bool)) or len(str(value)) > 64:
            raise ValueError
        result = Decimal(str(value))
        if not result.is_finite() or abs(result) > Decimal('1e18') or result.as_tuple().exponent < -12:
            raise ValueError
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise LedgerError('数值必须为有限十进制文本（最多12位小数）。') from None


def text_number(value):
    """输出 Decimal 文本，未知保留 null。"""
    if value is None:
        return None
    return format(value, 'f').rstrip('0').rstrip('.') if '.' in format(value, 'f') else str(value)


def symbol(value):
    """只接受 USD 正股代码，不解析期权合约或交易所货币。"""
    if not isinstance(value, str) or not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}', value):
        raise LedgerError('仅支持 USD 正股代码。')
    return value


def label(value, maximum=200, optional=False):
    """验证普通文本长度，拒绝控制字符但保留用户文字。"""
    if optional and value in (None, ''):
        return ''
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise LedgerError('文本为空、过长或含无效字符。')
    return value.strip()


def canonical(value):
    """生成确定性 JSON，用于冻结记录与预览摘要。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
