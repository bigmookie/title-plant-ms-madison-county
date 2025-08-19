# Document Reader

A document reader that reads documents (PDF, text) with two options:

1. **Document Reader AI (document_reader.py)** - Process documents with AI models for summarization, key information extraction, Q&A, and OCR correction
2. **Verbatim Text Extractor (verbatim_extractor.py)** - Extract text verbatim from documents without summarization, only correcting OCR errors

## Features

- Read PDF and text documents
- Process long documents by automatically splitting them into chunks
- **AI Mode**: Choose between OpenAI, Google Gemini, or Anthropic Claude models
- **AI Mode**: Multiple processing tasks: summarize, extract key information, answer questions, or correct OCR errors
- **Verbatim Mode**: Extract exact text from documents with only OCR corrections
- Command line interface for easy use

## Installation

1. Clone the repository
2. Install dependencies:
   ```
   pip install pypdf openai google-generativeai anthropic
   ```
3. Set up API keys in the script:
   - Update `OPENAI_API_KEY`, `GEMINI_API_KEY`, and `CLAUDE_API_KEY` with your API keys
   - Alternatively, set them as environment variables

## Usage

### AI Document Reader (document_reader.py)

```bash
# Summarize a document
python document_reader.py --file document.pdf --task summarize

# Extract key information
python document_reader.py --file document.pdf --task extract_key_info

# Answer a question about the document
python document_reader.py --file document.pdf --task answer --question "What is the main argument?"

# Correct OCR errors in the document with AI
python document_reader.py --file document.pdf --task correct_ocr

# Specify the AI model (1=OpenAI, 2=Google, 3=Claude)
python document_reader.py --file document.pdf --model 3

# Specify an output file
python document_reader.py --file document.pdf --output results.txt
```

### Verbatim Text Extractor (verbatim_extractor.py)

```bash
# Extract text verbatim from a document
python verbatim_extractor.py --file document.pdf

# Split large documents into chunks (specify chunk size in characters)
python verbatim_extractor.py --file document.pdf --chunk-size 10000

# Specify an output file
python verbatim_extractor.py --file document.pdf --output extracted.txt
```

### Options for document_reader.py

- `--file`: Path to the document (required)
- `--task`: Choose between `summarize`, `extract_key_info`, `answer`, or `correct_ocr`
- `--question`: Provide a question when using the `answer` task
- `--model`: Select AI model (1=OpenAI, 2=Google, 3=Claude)
- `--output`: Specify the output file path

### Options for verbatim_extractor.py

- `--file`: Path to the document (required)
- `--chunk-size`: Size in characters for splitting large documents (0 means no chunking)
- `--output`: Specify the output file path

## How It Works

1. The script reads the document text using appropriate readers based on file type
2. For long documents, it splits the text into overlapping chunks
3. Each chunk is processed using the selected AI model
4. For certain tasks (summarize, extract_key_info, answer), additional consolidation is performed to produce a cohesive result
5. The processed output is saved to a file and a preview is displayed

## Extending

- Add support for more file types by implementing additional reader functions
- Add more processing tasks by enhancing the `DOCUMENT_PROMPTS` dictionary
- Implement more sophisticated chunking strategies for specific document types

## License

MIT