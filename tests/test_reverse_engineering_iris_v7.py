from __future__ import annotations

import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.reverse_engineering_media_service import ObservationError
from app.services import reverse_engineering_iris_v7_service as iris


OWNED_HTML = """<!doctype html><html lang="pt"><head><meta charset="utf-8">
<style>body { background: linear-gradient(30deg, #123456, #102030); color: white }
h1 { font-size: 32px; }</style></head><body><main><h1 id="hero">BR-no-GTA</h1>
<p>Observar, medir e reconstruir.</p></main></body></html>"""


def _html(tmp_path, contents=OWNED_HTML):
    path=tmp_path/"owned.html"
    path.write_text(contents, encoding="utf-8")
    return path


def test_safe_owned_static_document_accepted(tmp_path):
    iris._owned_static_html(_html(tmp_path))


@pytest.mark.parametrize("unsafe", [
    "<script>alert(1)</script>",
    "<iframe src='https://example.org'></iframe>",
    "<img src='file:///etc/passwd'>",
    "<a href='http://127.0.0.1:9000/'>link</a>",
    "<form action='/submit'></form>",
    "<input type='password'>",
    "<style>@import 'https://example.org';</style>",
    "<style>body { background-image: url(http://169.254.169.254/); }</style>",
    "<div onclick='sendToken()'>bad</div>",
    "<base href='https://example.org'>",
])
def test_active_external_html_denied(tmp_path,unsafe):
    with pytest.raises(ObservationError,match="IRIS_LOCAL_HTML"):
        iris._owned_static_html(_html(tmp_path,OWNED_HTML.replace("</body>",unsafe+"</body>")))


@pytest.mark.parametrize("selector",["","h1;fetch('x')","https://site","h1\nh2","x"*110])
def test_selectors_fail_closed(tmp_path,selector):
    path=_html(tmp_path)
    with pytest.raises(ObservationError,match="IRIS_SELECTOR_UNSUPPORTED"):
        iris.capture_owned_static_page(
            source_path=path,output_path=tmp_path/"capture.png",
            iris_binary=tmp_path/"iris",selector=selector,
        )


def test_local_png_observation_has_real_dimensions_and_no_artistic_pass(tmp_path,monkeypatch):
    src=_html(tmp_path)
    binary=tmp_path/"iris"
    binary.write_bytes(b"fake-test-binary")
    monkeypatch.setattr(iris,"_iris_path",lambda p: binary)
    def fake_capture(argv,**kwargs):
        stage=Path(argv[argv.index("-o")+1])
        stage.write_bytes(b"\x89PNG\r\n\x1a\n"+b"\0\0\0\rIHDR"+
                          struct.pack(">II",960,600)+b"\x08\x02\0\0\0"+
                          b"\0\0\0\0"+b"FAKE")
        return SimpleNamespace(returncode=0,stdout=json.dumps({
            "status":"ok","url":src.as_uri(),"output":str(stage),"format":"png",
            "mode":"viewport","css_width":960,"css_height":600,
        })+"\n",stderr="")
    monkeypatch.setattr(iris.subprocess,"run",fake_capture)
    report=iris.capture_owned_static_page(
        source_path=src,output_path=tmp_path/"shot.png",iris_binary=binary,
    )
    assert report["status"]=="MEASURED"
    assert report["image_width"]==960 and report["image_height"]==600
    assert report["publication"]=="FORBIDDEN"
    assert report["live_website_capture"] is False
    assert report["mcp_registered"] is False
    assert report["artistic_quality_approved"] is False
    assert (tmp_path/"shot.png").stat().st_size>24
    assert len(report["evidence_sha256"])==64


def test_existing_file_cannot_be_overwritten(tmp_path,monkeypatch):
    p=_html(tmp_path)
    output=tmp_path/"shot.png"
    output.write_text("do not destroy")
    with pytest.raises(ObservationError,match="IRIS_OUTPUT_NOT_NEW_PRIVATE_PNG"):
        iris.capture_owned_static_page(source_path=p,output_path=output,
                                       iris_binary=tmp_path/"iris")
    assert output.read_text()=="do not destroy"


def test_wrong_pinned_iris_version_rejected(tmp_path,monkeypatch):
    binary=tmp_path/"iris"
    binary.write_bytes(b"fake")
    binary.chmod(0o700)
    monkeypatch.setattr(iris.subprocess,"run",lambda *args,**kwargs: SimpleNamespace(
        returncode=0,stdout="iris 9.9.9\n",stderr=""))
    with pytest.raises(ObservationError,match="IRIS_VERSION_UNPINNED"):
        iris._iris_path(binary)



def test_extended_iris_modes_are_bounded(tmp_path):
    page=_html(tmp_path)
    for kwargs,expected in [
        ({"full_page":True,"selector":"h1"},"IRIS_FULL_PAGE_SELECTOR_CONFLICT"),
        ({"padding":30},"IRIS_PADDING_UNSUPPORTED"),
        ({"selector":"h1","padding":49},"IRIS_PADDING_UNSUPPORTED"),
        ({"dark":"yes"},"IRIS_MODE_FLAGS_INVALID"),
        ({"wait_for":"a;alert(1)"},"IRIS_WAIT_FOR_UNSUPPORTED"),
    ]:
        with pytest.raises(ObservationError,match=expected):
            iris.capture_owned_static_page(
                source_path=page,output_path=tmp_path/"new.png",
                iris_binary=tmp_path/"iris",**kwargs,
            )


def test_iris_full_page_dark_and_selector_padding_translate_to_upstream_cli(tmp_path,monkeypatch):
    page=_html(tmp_path)
    binary=tmp_path/"iris"
    binary.write_bytes(b"test")
    monkeypatch.setattr(iris,"_iris_path",lambda path: binary)
    recorded=[]
    def fake_run(argv,**kwargs):
        recorded.append(argv)
        stage=Path(argv[argv.index("-o")+1])
        width,height=(960,1500) if "--full" in argv else (180,60)
        stage.write_bytes(b"\x89PNG\r\n\x1a\n"+b"\0\0\0\rIHDR"+
                          struct.pack(">II",width,height)+b"\x08\x02\0\0\0"+
                          b"\0\0\0\0"+b"FAKE")
        info={"status":"ok","url":page.as_uri(),"output":str(stage),
              "format":"png","mode":"full_page" if "--full" in argv else "element",
              "css_width":width,"css_height":height}
        if "--selector" in argv:
            info["selector"]="h1"
            info["padding"]=24
        return SimpleNamespace(returncode=0,stdout=json.dumps(info)+"\n",stderr="")
    monkeypatch.setattr(iris.subprocess,"run",fake_run)
    full=iris.capture_owned_static_page(
        source_path=page,output_path=tmp_path/"full.png",iris_binary=binary,
        full_page=True,dark=True,wait_for="h1",
    )
    element=iris.capture_owned_static_page(
        source_path=page,output_path=tmp_path/"element.png",iris_binary=binary,
        selector="h1",padding=24,dark=True,
    )
    assert ["--full"]==[x for x in recorded[0] if x=="--full"]
    assert "--dark" in recorded[0] and "--wait-for" in recorded[0]
    assert "--selector" in recorded[1] and "--padding" in recorded[1]
    assert full["capture_mode"]=="local_static_full_page"
    assert full["image_height"]==1500
    assert element["padding"]==24
    assert full["live_website_capture"] is False



def test_safe_dark_mode_media_query_is_allowed_without_enabling_imports(tmp_path):
    page=_html(tmp_path,OWNED_HTML.replace(
        "</style>","@media (prefers-color-scheme: dark){h1{color:white;background:black}}</style>"
    ))
    iris._owned_static_html(page)
    attacked=OWNED_HTML.replace("</style>","@import url(https://evil.test/file.css);</style>")
    with pytest.raises(ObservationError,match="IRIS_LOCAL_HTML_EXTERNAL_STYLES_FORBIDDEN"):
        iris._owned_static_html(_html(tmp_path,attacked))
