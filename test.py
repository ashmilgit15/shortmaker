import openai



client = openai.OpenAI(

    api_key="sk-147ff9cd6697408a8273b53c644d8487", 

    base_url="http://127.0.0.1:8045/v1"

)



response = client.chat.completions.create(

    model="claude-opus-4-6",
    messages=[{"role": "user", "content": "Hello!"}]

)

print(response.choices[0].message.content)