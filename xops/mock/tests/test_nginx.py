"""Tests for the nginx vhost generator — pure render functions + file I/O."""

from __future__ import annotations

from pathlib import Path

from xops.mock import nginx


def test_render_main_lists_each_vhost_include() -> None:
    out = nginx.render_main(hosts=("a.local", "b.local"))
    assert "include /etc/nginx/conf.d/vhost-a.local.conf;" in out
    assert "include /etc/nginx/conf.d/vhost-b.local.conf;" in out


def test_render_main_declares_upstream() -> None:
    out = nginx.render_main()
    assert f"upstream {nginx.UPSTREAM_NAME}" in out
    assert nginx.UPSTREAM_TARGET in out


def test_render_vhost_contains_tls_and_proxy_directives() -> None:
    out = nginx.render_vhost("mackolik.local")
    assert "listen 443 ssl;" in out
    assert "ssl_certificate" in out
    assert "/etc/nginx/certs/mackolik.local/leaf.key" in out
    assert f"proxy_pass http://{nginx.UPSTREAM_NAME}" in out
    assert "proxy_set_header Host mackolik.local;" in out


def test_render_vhost_includes_http_to_https_redirect() -> None:
    out = nginx.render_vhost("nesine.local")
    assert "listen 80;" in out
    assert "return 301 https://" in out


def test_render_main_is_deterministic() -> None:
    a = nginx.render_main(hosts=("x.local",))
    b = nginx.render_main(hosts=("x.local",))
    assert a == b


def test_write_all_creates_main_and_vhosts(tmp_path: Path) -> None:
    paths = nginx.write_all(hosts=("foo.local", "bar.local"), root=tmp_path)
    assert (tmp_path / "nginx.conf").exists()
    assert (tmp_path / "conf.d" / "vhost-foo.local.conf").exists()
    assert (tmp_path / "conf.d" / "vhost-bar.local.conf").exists()
    assert len(paths) == 3


def test_write_all_default_hosts(tmp_path: Path) -> None:
    nginx.write_all(root=tmp_path)
    for h in nginx.DEFAULT_HOSTS:
        assert (tmp_path / "conf.d" / f"vhost-{h}.conf").exists()
