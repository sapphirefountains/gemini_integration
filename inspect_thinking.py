
import google.genai.types as types
import inspect

try:
    print("ThinkingConfig fields:")
    print(inspect.signature(types.ThinkingConfig))
    print(dir(types.ThinkingConfig))
except Exception as e:
    print(e)
