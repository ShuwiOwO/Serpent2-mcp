"""End-to-end MCP protocol smoke test over stdio."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest


def _run(coro):
    return asyncio.run(coro)


def test_server_lists_tools_and_calls_tools(tmp_path):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    fake = tmp_path / "sss2"
    fake.write_text(
        "#!/bin/sh\n"
        'if [ $# -eq 0 ]; then echo "Usage: sss2 <inputfile> [options]"; '
        'echo "  --version"; exit 0; fi\n'
        'echo "fake serpent $@"\n'
        'base=$(basename "$1" .inp)\n'
        'cat > "${base}_res.m" <<EOF\n'
        "VERSION = 2;\nSIMULATION_COMPLETED = 1;\nANA_KEFF = [\n    1.02000E+00 0.00050\n];\nEOF\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    (tmp_path / "case.inp").write_text(
        'set title "smoke"\nsurf 1 sph 0 0 0 1\ncell 1 0 void -1\n'
        'cell 2 0 outside 1\nsrc 1 sp 0 0 0 se 1.0\nset nps 100\n'
        'set acelib "d.xsdata"\n',
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["SERPENT_DOCS_AUTO_SYNC"] = "0"
    env["SERPENT_MCP_WORKSPACE"] = str(tmp_path)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "serpent2_mcp"],
        cwd=str(tmp_path),
        env=env,
    )

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.instructions
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {
                    "get_card",
                    "search_docs",
                    "validate_input",
                    "run",
                    "job_status",
                    "get_results",
                    "plot_results",
                    "get_environment",
                    "install_photon_data",
                    "download_data_library",
                    "check_data_paths",
                    "setup_data",
                    "mcplib84_instructions",
                    "list_energy_structures",
                    "selfcheck",
                } <= names

                response = await session.call_tool("get_card", {"name": "surf"})
                assert "surf" in response.content[0].text

                example = (
                    Path(__file__).parents[1]
                    / "src"
                    / "serpent2_mcp"
                    / "knowledge"
                    / "examples"
                    / "02_pincell_criticality.inp"
                )
                target = tmp_path / "pin.inp"
                target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
                response = await session.call_tool("validate_input", {"input": str(target)})
                payload = response.content[0].text
                result = json.loads(payload.split("```json", 1)[1].rsplit("```", 1)[0])
                assert result["counts"]["error"] == 0

                response = await session.call_tool("run", {"input": "case.inp"})
                run_payload = json.loads(response.content[0].text)
                assert run_payload["state"] == "running"
                job_id = run_payload["job_id"]
                for _ in range(50):
                    response = await session.call_tool("job_status", {"job_id": job_id})
                    status = json.loads(response.content[0].text)
                    if status["state"] != "running":
                        break
                    await asyncio.sleep(0.1)
                assert status["state"] == "finished"
                assert status["exit_code"] == 0

                response = await session.call_tool(
                    "get_results", {"workdir": str(tmp_path), "input": "case"}
                )
                results = json.loads(response.content[0].text)
                assert results["summary"]["keff"]["ana_keff"]["mean"] == 1.02

                response = await session.call_tool("plot_results", {"kind": "keff", "workdir": str(tmp_path)})
                plot_text = response.content[0].text
                assert "NameError" not in plot_text and "not defined" not in plot_text

                response = await session.call_tool("get_environment", {})
                env_payload = json.loads(response.content[0].text)
                assert env_payload["executable"]["found"] is True
                assert "config" in env_payload

                response = await session.call_tool("mcplib84_instructions", {})
                instructions = json.loads(response.content[0].text)
                assert instructions["status"] == "missing"
                assert instructions["place_file_at"].endswith("xsdata/mcplib84")

                response = await session.call_tool("list_energy_structures", {})
                structures = json.loads(response.content[0].text)["structures"]
                assert any(item["name"] == "scale44" for item in structures)

                response = await session.call_tool("get_card", {"name": "sg"})
                resolved = json.loads(response.content[0].text)
                assert resolved["resolved_as"] == "parameter"
                assert resolved["card"] == "src"

                response = await session.call_tool("get_card", {"name": "ene"})
                ene = json.loads(response.content[0].text)
                assert "scale44" in ene["predefined_structures"]

    _run(scenario())
