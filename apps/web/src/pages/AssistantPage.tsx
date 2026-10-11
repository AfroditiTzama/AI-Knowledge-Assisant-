import {
  Bot,
  Info,
  LoaderCircle,
  Send,
  Sparkles,
  UserRound,
} from "lucide-react";
import {
  useState,
  type FormEvent,
} from "react";
import ReactMarkdown from "react-markdown";

import {
  askKnowledge,
  type KnowledgeSource,
} from "../api/chat";
import {
  getDocumentChunkPreviewByLocation,
} from "../api/documents";
import {
  getApiErrorMessage,
} from "../api/errors";
import {
  getWikiPage,
} from "../api/wiki";
import FeedbackBanner from "../components/FeedbackBanner";
import SourcePreviewDrawer, {
  type SourcePreviewContent,
} from "../components/SourcePreviewDrawer";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  retrievalMode?: string;
  sources?: KnowledgeSource[];
}

const suggestedQuestions = [
  "Summarize the main topics in my knowledge base.",
  "What are the most important findings across my documents?",
  "Compare the key ideas in my uploaded documents.",
  "Which sources support the main conclusions?",
];

export default function AssistantPage() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [failedQuestion, setFailedQuestion] = useState("");
  const [isSourcePreviewOpen, setIsSourcePreviewOpen] =
    useState(false);
  const [isSourcePreviewLoading, setIsSourcePreviewLoading] =
    useState(false);
  const [sourcePreviewError, setSourcePreviewError] = useState("");
  const [sourcePreviewContent, setSourcePreviewContent] =
    useState<SourcePreviewContent | null>(null);

  async function submitQuestion(value: string) {
    const cleanedQuestion = value.trim();

    if (!cleanedQuestion || isLoading) {
      return;
    }

    setError("");
    setFailedQuestion("");
    setQuestion("");
    setMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        role: "user",
        content: cleanedQuestion,
      },
    ]);
    setIsLoading(true);

    try {
      const response = await askKnowledge(cleanedQuestion);

      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: response.answer_markdown,
          retrievalMode: response.retrieval_mode,
          sources: response.sources,
        },
      ]);
    } catch (requestError) {
      setFailedQuestion(cleanedQuestion);
      setError(getApiErrorMessage(requestError));
    } finally {
      setIsLoading(false);
    }
  }

  async function openSourcePreview(source: KnowledgeSource) {
    setIsSourcePreviewOpen(true);
    setIsSourcePreviewLoading(true);
    setSourcePreviewError("");
    setSourcePreviewContent(null);

    try {
      if (
        (source.source_type === "wiki" ||
          source.source_type === "wiki_page") &&
        source.slug
      ) {
        const page = await getWikiPage(source.slug);

        setSourcePreviewContent({
          title: page.title,
          sourceLabel: "Compiled Wiki page",
          locationLabel: page.slug,
          text: page.content_markdown,
          score: source.score,
          isMarkdown: true,
        });
        return;
      }

      if (
        source.document_id &&
        source.chunk_index !== null
      ) {
        const preview =
          await getDocumentChunkPreviewByLocation(
            source.document_id,
            source.chunk_index,
          );

        setSourcePreviewContent({
          title: preview.document_filename,
          sourceLabel: "Original document",
          locationLabel:
            preview.page_number !== null
              ? `Page ${preview.page_number}`
              : `Chunk ${preview.chunk_index + 1}`,
          text: preview.text,
          score: source.score,
        });
        return;
      }

      setSourcePreviewError(
        "Preview is unavailable for this source.",
      );
    } catch (requestError) {
      setSourcePreviewError(getApiErrorMessage(requestError));
    } finally {
      setIsSourcePreviewLoading(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitQuestion(question);
  }

  return (
    <section className="page-container assistant-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Grounded intelligence</p>
          <h1>Knowledge Assistant</h1>
          <p>
            Ask questions across your Wiki and original document
            chunks, with traceable sources in every answer.
          </p>
        </div>
      </header>

      <div className="chat-panel">
        <div className="chat-messages">
          {messages.length === 0 ? (
            <div className="assistant-welcome">
              <div className="assistant-avatar">
                <Sparkles size={27} />
              </div>

              <p className="eyebrow">Your research copilot</p>
              <h2>Hi, I’m your Knowledge Assistant.</h2>
              <p>
                I answer questions using only your uploaded documents
                and compiled Wiki pages. Open any source card to inspect
                the evidence behind an answer.
              </p>

              <div className="assistant-info-note">
                <Info size={17} />
                <span>
                  Source score shows retrieval relevance, not the
                  probability that an answer is correct.
                </span>
              </div>

              <div className="suggestion-grid">
                {suggestedQuestions.map((suggestion) => (
                  <button
                    type="button"
                    key={suggestion}
                    onClick={() => void submitQuestion(suggestion)}
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((message) => (
              <article
                key={message.id}
                className={`chat-message ${message.role}`}
              >
                <div className="message-avatar">
                  {message.role === "user" ? (
                    <UserRound size={18} />
                  ) : (
                    <Bot size={18} />
                  )}
                </div>

                <div className="message-content">
                  <ReactMarkdown>{message.content}</ReactMarkdown>

                  {message.retrievalMode && (
                    <span className="retrieval-mode">
                      {message.retrievalMode}
                    </span>
                  )}

                  {message.sources && message.sources.length > 0 && (
                    <div className="source-list">
                      <div className="source-list-heading">
                        <h3>Sources</h3>
                        <span>Click to inspect</span>
                      </div>

                      {message.sources.map((source) => (
                        <button
                          type="button"
                          className="source-card"
                          key={`${message.id}-${source.source_id}`}
                          onClick={() =>
                            void openSourcePreview(source)
                          }
                        >
                          <strong>
                            {source.source_id}: {source.title}
                          </strong>
                          <span>
                            {source.source_type}
                            {source.page_number !== null
                              ? ` · page ${source.page_number}`
                              : ""}
                            {` · relevance ${source.score.toFixed(3)}`}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </article>
            ))
          )}

          {isLoading && (
            <div className="chat-message assistant">
              <div className="message-avatar">
                <Bot size={18} />
              </div>
              <div className="message-content typing-message">
                <LoaderCircle className="spin" size={19} />
                Searching your knowledge base...
              </div>
            </div>
          )}
        </div>

        {error && (
          <div className="chat-feedback">
            <FeedbackBanner
              kind="error"
              message={error}
              onRetry={
                failedQuestion
                  ? () => void submitQuestion(failedQuestion)
                  : undefined
              }
            />
          </div>
        )}

        <form className="chat-composer" onSubmit={handleSubmit}>
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask a question about your knowledge base..."
            rows={2}
            disabled={isLoading}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submitQuestion(question);
              }
            }}
          />

          <button
            type="submit"
            className="primary-button icon-button"
            disabled={isLoading || question.trim().length < 2}
            aria-label="Send question"
          >
            <Send size={19} />
          </button>
        </form>
      </div>

      <SourcePreviewDrawer
        isOpen={isSourcePreviewOpen}
        isLoading={isSourcePreviewLoading}
        error={sourcePreviewError}
        content={sourcePreviewContent}
        onClose={() => setIsSourcePreviewOpen(false)}
      />
    </section>
  );
}
