"""Tests for malibu.__main__ — CLI argument parser."""

from __future__ import annotations

from malibu.__main__ import _build_parser


class TestCLIParser:
    def test_server_command(self):
        parser = _build_parser()
        args = parser.parse_args(["server"])
        assert args.command == "server"

    def test_client_command(self):
        parser = _build_parser()
        args = parser.parse_args(["client", "echo", "hello"])
        assert args.command == "client"
        assert args.agent_cmd == ["echo", "hello"]
        assert args.cwd == "."

    def test_client_with_cwd(self):
        parser = _build_parser()
        args = parser.parse_args(["client", "--cwd", "/home/user", "echo"])
        assert args.cwd == "/home/user"
        assert args.agent_cmd == ["echo"]

    def test_duet_command(self):
        parser = _build_parser()
        args = parser.parse_args(["duet"])
        assert args.command == "duet"
        assert args.cwd == "."

    def test_duet_with_cwd(self):
        parser = _build_parser()
        args = parser.parse_args(["duet", "--cwd", "/project"])
        assert args.cwd == "/project"

    def test_generate_key_command(self):
        parser = _build_parser()
        args = parser.parse_args(["generate-key"])
        assert args.command == "generate-key"

    def test_no_command(self):
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.command is None
