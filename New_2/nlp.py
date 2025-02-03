import spacy

# Załaduj model językowy spaCy
nlp = spacy.load('en_core_web_sm')

def interpret_query(query):
    doc = nlp(query.lower())
    
    # Proste słowa kluczowe do interpretacji zapytań
    if "average goals" in query or "average number of goals" in query:
        return "average_goals"
    elif "average corners" in query or "corners on average" in query:
        return "average_corners"
    elif "average yellow cards" in query or "yellow cards per match" in query:
        return "average_yellow_cards"
    elif "average shots" in query or "shots on target" in query:
        return "average_shots"
    else:
        return "unknown_query"

if __name__ == '__main__':
    # Przykładowe zapytania do testowania
    test_queries = [
        "What is the average number of goals?",
        "How many corners on average?",
        "Tell me the average yellow cards per match.",
        "What are the average shots on target?"
    ]

    for query in test_queries:
        interpreted_query = interpret_query(query)
        print(f"Query: {query} -> Interpreted as: {interpreted_query}")