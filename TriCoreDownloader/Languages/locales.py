import importlib
from pathlib import Path

STRINGS = {}

# Get the path of the 'Languages' folder (where this script is located)
current_dir = Path(__file__).parent

# Automatically iterate through all files starting with "locales_" and ending with ".py"
for file_path in current_dir.glob("locales_*.py"):
    module_name = file_path.stem  # e.g., "locales_fr"
    
    # Extract the language code (e.g., "fr")
    parts = module_name.split("_")
    if len(parts) >= 2:
        lang_code = parts[1].lower()
        
        try:
            # Dynamically import the detected module
            module = importlib.import_module(f".{module_name}", package=__package__)
            
            # Automatically search for the dictionary (e.g., STRINGS_FR)
            dict_name = f"STRINGS_{lang_code.upper()}"
            
            if hasattr(module, dict_name):
                STRINGS[lang_code] = getattr(module, dict_name)
                
        except Exception as e:
            print(f"[!] Error loading language '{lang_code}': {e}")