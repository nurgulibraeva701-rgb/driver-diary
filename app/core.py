"""Бизнес-логика: валидация, сводка, хранилище. Без внешних зависимостей."""
import json, os, tempfile, threading
from datetime import datetime

PAYMENTS = ("cash", "card")


class ValidationError(ValueError):
    pass


class Conflict(Exception):
    pass


def _dt(value, field):
    if not isinstance(value, str):
        raise ValidationError(f"{field}: ожидается строка ISO 8601")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"{field}: неверный формат даты/времени")
    if dt.tzinfo is None:
        raise ValidationError(f"{field}: укажите часовой пояс, например +05:00")
    return dt


def _num(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field}: ожидается число")
    return value


def validate(t):
    """Проверяет поездку и возвращает нормализованную копию."""
    if not isinstance(t, dict):
        raise ValidationError("тело запроса должно быть объектом JSON")
    tid = t.get("id")
    if not isinstance(tid, str) or not tid.strip():
        raise ValidationError("id: обязательная непустая строка")
    start, end = _dt(t.get("start"), "start"), _dt(t.get("end"), "end")
    if end <= start:
        raise ValidationError("end должен быть позже start")
    amount = _num(t.get("amount"), "amount")
    if amount <= 0:
        raise ValidationError("amount должна быть больше 0")
    commission = _num(t.get("commission"), "commission")
    if commission < 0 or commission > amount:
        raise ValidationError("commission должна быть в диапазоне 0..amount")
    if t.get("payment") not in PAYMENTS:
        raise ValidationError("payment: cash или card")
    return {"id": tid.strip(), "start": start.isoformat(), "end": end.isoformat(),
            "amount": amount, "payment": t["payment"], "commission": commission}


def day_of(trip):
    """Дата поездки = дата начала в часовом поясе самой поездки."""
    return datetime.fromisoformat(trip["start"]).date().isoformat()


def _r(x):
    x = round(x, 2)
    return int(x) if x == int(x) else x


def summarize(trips):
    s = {"trips": 0, "revenue": 0, "commission": 0, "net": 0,
         "cash": {"trips": 0, "amount": 0}, "card": {"trips": 0, "amount": 0}}
    for t in trips:
        s["trips"] += 1
        s["revenue"] += t["amount"]
        s["commission"] += t["commission"]
        s[t["payment"]]["trips"] += 1
        s[t["payment"]]["amount"] += t["amount"]
    s["net"] = s["revenue"] - s["commission"]  # «на руки»
    for k in ("revenue", "commission", "net"):
        s[k] = _r(s[k])
    for k in ("cash", "card"):
        s[k]["amount"] = _r(s[k]["amount"])
    return s


class Store:
    def __init__(self, path):
        self.path, self._lock = path, threading.Lock()
        self._trips = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for t in json.load(f):
                    t = validate(t)
                    self._trips[t["id"]] = t

    def _save(self):
        d = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(list(self._trips.values()), f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def days(self):
        with self._lock:
            return sorted({day_of(t) for t in self._trips.values()})

    def list(self, day):
        with self._lock:
            return sorted((t for t in self._trips.values() if day_of(t) == day),
                          key=lambda t: datetime.fromisoformat(t["start"]))

    def add(self, raw):
        """Возвращает (поездка, created). Повтор той же поездки идемпотентен;
        тот же id с другими данными -> Conflict."""
        t = validate(raw)
        with self._lock:
            old = self._trips.get(t["id"])
            if old is not None:
                if old == t:
                    return old, False
                raise Conflict(f"поездка {t['id']} уже есть с другими данными")
            self._trips[t["id"]] = t
            self._save()
            return t, True
