import streamlit as st

import textwrap

import google.generativeai as genai
import google

from markdown import markdown

import pandas as pd
import json
from wordcloud import WordCloud
from matplotlib.colors import LinearSegmentedColormap

from utils.google import read_data_from_cloud, _get_creds
from utils.dbbact import get_dbbact_response
import requests

import asyncio

creds = _get_creds()

genai.configure(api_key=creds["GEMINI_API"]["API_KEY"])

model = genai.GenerativeModel('gemini-pro')

chat = None

def get_id_from_data(data, id):
    if id in data.keys():
        if data[id]["kit_id"] != 0:
            return data[id]
    return {}

def generate_wordcloud(terms_scores):
    def color_func(word, font_size, position, orientation, random_state, **kwargs):
        cmap = LinearSegmentedColormap.from_list("costum", ["#4dff88", "#33ff77", "#1aff66", "#00ff55", "#00e64d", "#00cc44", "#00b33c", "#009933", "#00802b", "#006622", "#004d1a", "#003311", "#001a09", "#000000"])
        cmap_negative = LinearSegmentedColormap.from_list("custom", ["#ff8080", "#ff6666", "#ff4d4d", "#ff3333", "#ff1a1a", "#ff0000"])


        score = terms_scores.get(word, 0)
        if word.startswith("-"):
            color = cmap_negative(score)
        else:
            color = cmap(score)
        rgb_color = tuple(int(x * 255) for x in color[:3])

        return f"rgb{rgb_color}"
    
    return WordCloud(collocations=False, width=1500, height=800, background_color="white", color_func=color_func).generate_from_frequencies(terms_scores)

async def get_bot_response(user_input):
    global chat
    wordcloud = None
    chat = model.start_chat()

    with st.spinner("Initializing..."):
        response = await chat.send_message_async("""From now on, you are a microbiome chatbot. You will answer to student's questions according to the data I will provide you. The data I will provide you later will be as a json. you do not show the json to the students. The data is details about a bacteria with the id that is written in the "bacteria_id" field, this bacteria was found in a sample of the kit id that is written in the "kit_id" field, bacteria's annotations are in the "annotations" field and its fscores are in the "fscores" field. Your answer should be summerized in a few paragraphs and not as a list. be kind. maybe there will be questions that are not related to the bacterias and the microbiome, these questions will be called "General", for these questions you will answer as a simple bot. The questions that is related to the microbiome and bacterias will be called "Microbiome" and you will answer them based on the data I will provide you. Maybe you will get an empty curly brackets (empty data), in that case you will asnwer this message: "I didn't find bacterias with this id." """)
    
    with st.spinner("Thinking..."):
        response = await chat.send_message_async(f"What is the type of the message ({user_input})? Microbiome or General? (Write one word)")

        question_type = response.text

        document = {}

        if question_type == "Microbiome":
            response = chat.send_message(f"""In the following phrase it asked for specific bacteria id:
{user_input}
give me only the id number""")
            print(response.text)
            
            try:
                id = str(int(response.text))
            except ValueError:
                raise ValueError(f"{response.text} can't be int")
            
            data = read_data_from_cloud()

            document = get_id_from_data(data, id)
            if document:
                try:
                    dbbact_data = get_dbbact_response(document["sequences"])
                except requests.exceptions.JSONDecodeError:
                    dbbact_data = {}

                document = {
                    **document,
                    **dbbact_data
                }

                message = f"""This is an information about bacteria with a specific id, read this inforamtion and then answer on the question:

this is inforamtion about the bacteria id {id}, its taxonoy is: {"The bacteira's Kingdom is " + document["Kingdom"] if document["Kingdom"] != '__' else ''}, {"The bacteira's Phylum is " + document["Phylum"] if document["Phylum"] != '__' else ''}, {"The bacteira's Class is " + document["Class"] if document["Class"] != '__' else ''}, {"The bacteira's Order is " + document["Order"] if document["Order"] != '__' else ''}, {"The bacteira's Family is " + document["Family"] if document["Family"] != '__' else ''}, {"The bacteira's Genus is " + document["Genus"] if document["Genus"] != '__' else ''}, {"The bacteira's Species is " + document["Species"] if document["Species"] != '__' else ''}.
Its annotations are:
""" 
                try:
                    for annotation in document["annotations"]:
                        annotation["text"] = annotation["text"].rstrip(" ").lstrip(" ")
                        annotation["text"] = annotation["text"].replace("common", "it was observed in over half of the samples in").replace("dominant", "it was observed as highly dominant in samples from an experiment examining").replace("high in", "in a microbiome experiment, it was observed to be in higher mean frequency in")

                        message += f"\n{annotation['text']} ({annotation['link']})"
                except KeyError:
                    message += "No annotation found\n"

                message += "Its fscores are:\n"
                try:
                    for fscore_name, fscore_value in document["fscores"].items():
                        message += f"{fscore_name}: {fscore_value}\n"
                except KeyError:
                    message += "No fscores found\n"
                message += f"""
Answer in summerized paragraphs on this question:
{user_input}"""
                try:
                    response = await chat.send_message_async(message)
                    answer = response.text
                except google.api_core.exceptions.InternalServerError:
                    answer = "I'm sorry, an error accured. Please try again later."
            else:
                answer = "I couldn't find the bacteria with this id."
            with st.spinner("Generating word cloud..."):
                if question_type == "Microbiome":
                    if document:
                        df_scores = pd.DataFrame.from_dict({"fscore_name": [fscore_name for fscore_name in document["fscores"].keys()],
                                                            "fscore_value": [fscore_value for fscore_value in document["fscores"].values()]})
                        terms_scores = dict(zip(df_scores['fscore_name'], df_scores['fscore_value']))
                        wordcloud = generate_wordcloud(terms_scores)
        else:
            answer = await chat.send_message_async(user_input)
        bot_response = markdown(textwrap.indent(answer.replace('•', ' *'), '> ', predicate=lambda _: True))

    
    return bot_response, wordcloud

async def chat_microbiome():
    st.title("Microbiome Bacteria Chatbot")
    st.sidebar.title("General Information")

    conversation_history = []

    user_input = st.text_input("You:", key="user_input")
    send_pressed = st.button("Send")
    if send_pressed and user_input:
        conversation_history.append({"role": "user", "message": user_input})

        bot_response, wordcloud = await get_bot_response(user_input)

        conversation_history.append({"role": "bot", "message": bot_response})
        
        if wordcloud:
            st.image(wordcloud.to_array(), caption="Word Cloud", use_column_width=True)

    for entry in conversation_history:
        role = entry['role']
        message = entry['message']

        if role == "user":
            st.markdown(f'<div style="padding: 10px; background-color: #7D7C7C; border-radius: 10px; margin-bottom: 10px;">'
                        f'<span style="color: #fff; font-weight: bold;">You: {message}</span></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div style="padding: 10px; background-color: #7D7C7C; border-radius: 10px;">'
                        f'<span style="color: #fff; font-weight: bold;">Bot:  {message}</span></div>', unsafe_allow_html=True)
            
    st.sidebar.markdown("### Chatbot Information")
    st.sidebar.info("This is a chatbot that gives information about Bactrias in the Microbiome project.")
    st.sidebar.markdown("### Instructions")
    st.sidebar.text("1. Enter yout message in the input field.")
    st.sidebar.text("2. Click the 'Send' button to interact with the chatbot.")
    st.sidebar.text("3. The chatbot will answer you on the question based on the current data.")

async def main():
    await chat_microbiome()

if __name__ == '__main__':
    asyncio.run(main())