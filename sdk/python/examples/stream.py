from atlas_sdk import Atlas

for event in Atlas().stream("Summarize the current directory in one sentence.", cwd="."):
    print(event)
