import os
from openai import AzureOpenAI

endpoint = "https://stan4-mepy2tb7-eastus2.cognitiveservices.azure.com/"
model_name = "gpt-4o-mini"
deployment = "gpt-4o-mini"

subscription_key = "9H3bmC2RsTMwAWAl4bgKwKDqgByPVmSdhrN6kUpnYeWDEovqX7ilJQQJ99BHACHYHv6XJ3w3AAAAACOGrGlc"
api_version = "2024-12-01-preview"

client = AzureOpenAI(
    api_version=api_version,
    azure_endpoint=endpoint,
    api_key=subscription_key,
)

response = client.chat.completions.create(
    messages=[
        {
            "role": "system",
            "content": "You are a helpful assistant.",
        },
        {
            "role": "user",
            "content": "Generate a syllabus",
        }
    ],
    max_tokens=4096,
    temperature=1.0,
    top_p=1.0,
    model=deployment
)

print(response.choices[0].message.content)


