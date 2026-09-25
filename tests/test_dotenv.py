import pytest

from envvault import dotenv


def test_parse_common_syntax():
    text = """﻿# comentario
TOKEN=abc123
export CLIENT_ID = 42
EMPTY=
SPACED =  hola mundo   # comentario al final
HASH=abc#def
SINGLE='sin $interpolar \\n'
DOUBLE="linea1\\nlinea2 \\"citado\\""
COLON: yaml-like
malformada sin igual
MULTI="-----BEGIN KEY-----
abc
-----END KEY-----"
BACKTICK=`hola`
"""
    values = dotenv.parse(text)
    assert values == {
        "TOKEN": "abc123",
        "CLIENT_ID": "42",
        "EMPTY": "",
        "SPACED": "hola mundo",
        "HASH": "abc#def",
        "SINGLE": "sin $interpolar \\n",
        "DOUBLE": 'linea1\nlinea2 "citado"',
        "COLON": "yaml-like",
        "MULTI": "-----BEGIN KEY-----\nabc\n-----END KEY-----",
        "BACKTICK": "hola",
    }


def test_crlf_and_unterminated_quote():
    assert dotenv.parse('A=1\r\nB="sin cerrar\r\nC=3') == {"A": "1", "B": "sin cerrar\nC=3"}


@pytest.mark.parametrize("value", [
    "simple", "", "con espacios", "comilla ' simple", 'doble " y \\ barra', "multi\nlínea", "$HOME ${X}",
    "a#b", " espacio delante",
])
def test_dump_roundtrip(value):
    text = dotenv.dump({"KEY": value})
    assert dotenv.parse(text) == {"KEY": value}


def test_dump_with_header_and_notes():
    text = dotenv.dump({"A": "1", "B": "2"}, header="Cabecera\nsegunda", notes={"B": "para qué"})
    assert text == "# Cabecera\n# segunda\n\nA=1\n# para qué\nB=2\n"
