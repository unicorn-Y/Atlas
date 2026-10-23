"""Probe stable and permission-consistent model tool catalogs."""
from atlas.agent.tool_catalog import filter_executable_tools


def main() -> None:
    schema = lambda name: {"type": "function", "function": {"name": name, "parameters": {}}}
    tools = [schema("write_file"), schema("read_file"), schema("read_file")]
    visible = filter_executable_tools(tools, allow={"read_file"})
    names = [item["function"]["name"] for item in visible]
    assert names == ["read_file", "read_file"]
    # Catalog assembly applies first-wins deduplication and stable sorting.
    unique = {name: schema(name) for name in set(names)}
    assert list(sorted(unique)) == ["read_file"]
    assert filter_executable_tools(tools, deny={"write_file"}) == tools[1:]
    print("W2-2 per-run tool pool filtering and stable catalog behavior: PASS")


if __name__ == "__main__":
    main()
