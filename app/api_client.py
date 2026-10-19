"""Thin client for the Moonswitch API. Errors surface as ApiError with the server's message."""
import requests
import streamlit as st


class ApiError(Exception):
    pass


def _call(method: str, path: str, body: dict | None = None):
    r = requests.request(
        method, st.secrets["API_URL"].rstrip("/") + path, json=body,
        headers={"x-api-key": st.secrets["API_KEY"]}, timeout=20,
    )
    try:
        data = r.json()
    except ValueError:
        raise ApiError(f"HTTP {r.status_code}: {r.text[:200]}")
    if r.status_code >= 400:
        raise ApiError(data.get("error") or data.get("message") or f"HTTP {r.status_code}")
    return data


def get(path):
    return _call("GET", path)


def post(path, body=None):
    return _call("POST", path, body or {})


def patch(path, body):
    return _call("PATCH", path, body)


def delete(path, body=None):
    return _call("DELETE", path, body)


@st.cache_data(ttl=300)
def config() -> dict:
    return get("/config")


def run(fn, *args, success: str | None = None) -> bool:
    """Call a write; show the error (or a toast) instead of a stack trace."""
    try:
        fn(*args)
    except ApiError as e:
        st.error(str(e))
        return False
    if success:
        st.toast(success)
    return True
