"""
RAG Engine Module for PEP Merchandising Intelligence Assistant

This module implements the core Retrieval-Augmented Generation (RAG) functionality:
- Document loading and processing
- Vector embeddings and similarity search
- Conversational AI chain with memory
- Integration with OpenAI's language models

KEY CONCEPTS FOR JUNIOR DEVELOPERS:
1. RAG (Retrieval-Augmented Generation): Combines document retrieval with AI generation
   - First retrieves relevant documents from a knowledge base
   - Then uses those documents as context for generating responses
   
2. Vector Store: Converts documents into numerical representations (embeddings)
   - Enables semantic search (finding similar meaning, not just keywords)
   - FAISS is used for fast similarity search
   
3. Embeddings: Mathematical representations of text that capture meaning
   - Similar concepts have similar embeddings
   - Allows AI to find relevant context even with different wording
"""

import os
import streamlit as st
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import TextLoader, PyPDFLoader, Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.output_parsers import StrOutputParser
from config import DOCS_DIR, FAISS_DIR, CHUNK_SIZE, CHUNK_OVERLAP, MODEL, TEMPERATURE, SEARCH_K


@st.cache_resource
def get_embeddings():
    """
    Initialize OpenAI embeddings model for converting text to vectors.
    
    WHAT IS AN EMBEDDING?
    - A numerical representation of text (list of numbers)
    - Similar texts have similar embeddings
    - Example: "cat" and "kitten" have more similar embeddings than "cat" and "car"
    
    WHY CACHE THIS? (@st.cache_resource decorator)
    - Embeddings model is expensive to initialize
    - Caching keeps it in memory across Streamlit reruns
    - Only creates the model once, reuses it thereafter
    
    Returns:
        OpenAIEmbeddings: Model that converts text to 1536-dimensional vectors
    """
    return OpenAIEmbeddings(model="text-embedding-3-small")


def load_all_documents():
    """
    Load all supported documents from the documents directory.
    
    WHAT THIS DOES:
    - Scans the DOCS_DIR folder for files
    - Loads each file using appropriate loader based on file type
    - Returns a list of LangChain Document objects
    
    DOCUMENT LOADERS:
    - TextLoader: For .txt and .md files (plain text/markdown)
    - PyPDFLoader: For .pdf files (extracts text from PDFs)
    - Docx2txtLoader: For .docx files (Microsoft Word documents)
    
    DOCUMENT STRUCTURE:
    Each Document object has:
    - page_content: The actual text content
    - metadata: Dictionary with info like {"source": "filename.pdf"}
    
    Returns:
        list: List of Document objects containing loaded text and metadata
    """
    # Check if documents directory exists, return empty list if not
    if not os.path.exists(DOCS_DIR):
        return []
    
    documents = []
    
    # Iterate through all files in the documents directory
    for filename in os.listdir(DOCS_DIR):
        filepath = os.path.join(DOCS_DIR, filename)
        
        # Skip directories, only process files
        if not os.path.isfile(filepath):
            continue
        
        try:
            # Select appropriate loader based on file extension
            if filename.endswith(('.txt', '.md')):
                loader = TextLoader(filepath, encoding="utf-8")
            elif filename.endswith('.pdf'):
                loader = PyPDFLoader(filepath)
            elif filename.endswith('.docx'):
                loader = Docx2txtLoader(filepath)
            else:
                # Skip unsupported file types
                continue
            
            # Load the document (returns list of Document objects)
            docs = loader.load()
            
            # Add source filename to metadata for each document
            # This helps track where information came from
            for doc in docs:
                doc.metadata["source"] = filename
            
            # Add all loaded documents to our collection
            documents.extend(docs)
            
        except Exception as e:
            # Show warning in Streamlit UI if file fails to load
            st.warning(f"Error loading {filename}: {str(e)}")
    
    return documents


@st.cache_resource
def load_vector_store():
    """
    Load existing FAISS vector store or create a new one from documents.
    
    WHAT IS A VECTOR STORE?
    - Database that stores document embeddings (numerical representations)
    - Enables fast similarity search to find relevant documents
    - FAISS = Facebook AI Similarity Search (optimized for speed)
    
    WHY CHUNK DOCUMENTS?
    - Large documents are split into smaller chunks
    - Smaller chunks = more precise retrieval
    - Overlap ensures context isn't lost between chunks
    - Example: 1000-character chunks with 200-character overlap
    
    WORKFLOW:
    1. Try to load existing vector store (if previously created)
    2. If not found, create new one:
       a. Load all documents
       b. Split into chunks
       c. Convert chunks to embeddings
       d. Save to disk for future use
    
    Returns:
        FAISS: Vector store object for similarity search, or None if no documents
    """
    # Get the embeddings model for converting text to vectors
    embeddings = get_embeddings()
    
    # Try loading existing vector store from disk (faster than recreating)
    if os.path.exists(os.path.join(FAISS_DIR, "index.faiss")):
        # allow_dangerous_deserialization=True needed for loading pickle files
        return FAISS.load_local(FAISS_DIR, embeddings, allow_dangerous_deserialization=True)
    
    # No existing store found, create new one
    docs = load_all_documents()
    if not docs:
        # No documents to process
        return None
    
    # Split documents into smaller chunks for better retrieval
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,        # Max characters per chunk (e.g., 1000)
        chunk_overlap=CHUNK_OVERLAP   # Characters to overlap between chunks (e.g., 200)
    )
    chunks = splitter.split_documents(docs)
    
    # Create vector store: converts chunks to embeddings and builds search index
    store = FAISS.from_documents(chunks, embeddings)
    
    # Save to disk so we don't have to recreate next time
    store.save_local(FAISS_DIR)
    
    return store


def get_chat_chain():
    """Create RAG chain with memory."""
    vector_store = load_vector_store()
    
    if not vector_store:
        return None
    
    llm = ChatOpenAI(model_name=MODEL, temperature=TEMPERATURE)
    retriever = vector_store.as_retriever(search_kwargs={"k": SEARCH_K})
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are the PEP Merchandising Intelligence Assistant, an expert advisor for PEP's Buying, Planning & Merchandising teams. PEP is South Africa's largest single brand retailer, serving millions of customers with affordable clothing, footwear, and homeware.

Your mission is to empower merchandising professionals with instant access to critical business intelligence, policies, procedures, and supplier information to drive better buying decisions and operational excellence.

Knowledge Base:
{context}

Available documents: {document_list}

Core Responsibilities:
1. **Merchandising Intelligence**: Provide accurate information on buying procedures, supplier management, pricing strategies, performance metrics, and compliance standards.

2. **Data-Driven Insights**: When discussing KPIs, margins, or performance benchmarks, present information clearly with specific numbers, targets, and calculations when available.

3. **Operational Guidance**: Help users navigate PEP's internal processes for purchase orders, approvals, vendor onboarding, quality standards, and compliance requirements.

4. **Supplier Intelligence**: Provide vendor details, contact information, lead times, payment terms, quality ratings, and performance history when queried.

Response Guidelines:

**Accuracy First**: Only provide information directly from the knowledge base documents. If information isn't available, clearly state: "I don't have that specific information in the current knowledge base. Please check with your department head or email merchandising@pep.co.za for clarification."

**Structure & Clarity**:
- Use bullet points and numbered lists for procedures
- Present calculations and formulas clearly
- Include specific figures, percentages, and targets when available
- Break complex processes into step-by-step instructions

**Professional Tone**: 
- Direct and business-focused
- Use merchandising terminology appropriately
- Concise but comprehensive
- Action-oriented language

**Context Awareness**:
- Reference specific PEP policies and document sources
- Distinguish between different product categories when relevant (clothing vs. footwear vs. homeware)
- Note approval hierarchies and escalation paths
- Highlight compliance requirements and deadlines

**Practical Support**:
- Provide contact extensions for department heads when relevant
- Reference approval thresholds and authorization levels
- Include turnaround times and lead time expectations
- Suggest next steps for implementation

**What You Do**: Answer questions about buying procedures, supplier directories, pricing formulas, margin calculations, performance benchmarks, KPIs, compliance standards, merchandising guidelines, vendor management, purchase order processes, quality standards, and operational policies.

**What You Don't Do**: Access live inventory systems, approve purchase orders, modify supplier contracts, process payments, or make strategic business decisions. For these, direct users to appropriate personnel.

Remember: You're an internal business intelligence tool designed to make PEP's merchandising operations faster, smarter, and more efficient. Empower teams with the knowledge they need to serve PEP's customers better."""),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}")
    ])
    
    def format_docs(docs):
        return "\n\n".join(doc.page_content for doc in docs)
    
    def get_context(input_dict):
        """Extract context from input."""
        user_input = input_dict.get("input", "")
        docs = retriever.invoke(user_input)
        return format_docs(docs)
    
    def get_document_list_str(input_dict):
        """Get list of uploaded documents."""
        from config import get_document_list
        docs = get_document_list()
        if docs:
            return ", ".join(docs)
        return "No documents uploaded"
    
    chain = (
        {
            "input": lambda x: x["input"],
            "chat_history": lambda x: x.get("chat_history", []),
            "context": get_context,
            "document_list": get_document_list_str
        }
        | prompt
        | llm
        | StrOutputParser()
    )
    
    if "session_histories" not in st.session_state:
        st.session_state.session_histories = {}
    
    return RunnableWithMessageHistory(
        chain,
        get_session_history=lambda sid: st.session_state.session_histories.setdefault(
            sid, ChatMessageHistory()
        ),
        input_messages_key="input",
        history_messages_key="chat_history"
    )