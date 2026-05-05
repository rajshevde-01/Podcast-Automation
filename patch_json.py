import json

def fix_json():
    with open("world_channels.txt", "r") as f:
        lines = f.readlines()
        
    id_map = {}
    for line in lines:
        if ":" in line:
            parts = line.strip().split(": ")
            if len(parts) == 2 and not "failed" in parts[1] and not "HTTP" in parts[1]:
                id_map[parts[0]] = parts[1]
                
    # Manual overrides based on web search overrides and fixes
    id_map["OfficialFlagrant"] = "UC64S-R52h5z4k7u9_5v7CPA"

    with open("podcasts_list.json", "r") as f:
        data = json.load(f)
        
    for p in data["world_top_20"]:
        url = p["url"]
        handle = url.rsplit("@", 1)[-1]
        
        if handle == "Flagrant":
            p["url"] = "https://www.youtube.com/@OfficialFlagrant"
            handle = "OfficialFlagrant"
            
        if handle in id_map:
            p["channel_id"] = id_map[handle]
            
    with open("podcasts_list.json", "w") as f:
        json.dump(data, f, indent=2)

if __name__ == "__main__":
    fix_json()
