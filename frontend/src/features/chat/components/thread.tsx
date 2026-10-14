"use client";

import { downloadSource } from "@/lib/api-client";
import { report } from "@/features/chat/actions";
import { ModelSelector } from "@/features/chat/components/model-selector";
import { useThreadStore, type Citation } from "@/features/chat/store";
import {
  UserMessageAttachments,
} from "@/features/chat/components/attachment";
import { MarkdownText } from "@/features/chat/components/markdown-text";
import { ToolFallback } from "@/features/chat/components/tool-fallback";
import { TooltipIconButton } from "@/components/ui/tooltip-icon-button";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  ActionBarMorePrimitive,
  ActionBarPrimitive,
  AuiIf,
  BranchPickerPrimitive,
  ComposerPrimitive,
  ErrorPrimitive,
  MessagePrimitive,
  SuggestionPrimitive,
  ThreadPrimitive,
  useAuiState,
} from "@assistant-ui/react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CopyIcon,
  DownloadIcon,
  MoreHorizontalIcon,
  PencilIcon,
  RefreshCwIcon,
  SparklesIcon,
  SquareIcon,
} from "lucide-react";
import { useEffect, useRef, type FC } from "react";

// When the AI finishes responding, scroll the last user message into view so the
// Wait for two animation frames so the library has painted messages before we scroll.
const afterPaint = (fn: () => void) => {
  requestAnimationFrame(() => requestAnimationFrame(fn));
};

const scrollToLastUserMessage = (behavior: ScrollBehavior) => {
  const userMsgs = document.querySelectorAll('[data-role="user"]');
  const last = userMsgs[userMsgs.length - 1] as HTMLElement | undefined;
  last?.scrollIntoView({ block: "start", behavior });
};

const ScrollController: FC = () => {
  const isRunning = useThreadStore((s) => !!s.runningThreads[s.currentThreadId]);
  const currentThreadId = useThreadStore((s) => s.currentThreadId);
  const wasRunningRef = useRef(false);

  // After a response finishes, scroll back to the question that triggered it.
  useEffect(() => {
    if (wasRunningRef.current && !isRunning) {
      afterPaint(() => scrollToLastUserMessage("smooth"));
    }
    wasRunningRef.current = isRunning;
  }, [isRunning]);

  // When switching threads, wait for messages to paint then jump to last user message.
  useEffect(() => {
    afterPaint(() => scrollToLastUserMessage("instant"));
  }, [currentThreadId]);

  return null;
};

// Shared avatar shown left of every assistant turn (real or generating).
const AssistantAvatar: FC<{ pulse?: boolean }> = ({ pulse = false }) => (
  <div className="mt-0.5 shrink-0 size-7 rounded-full bg-gradient-to-br from-violet-500 to-indigo-500 flex items-center justify-center shadow-sm">
    <SparklesIcon className={cn("size-3.5 text-white", pulse && "animate-pulse")} />
  </div>
);

export const Thread: FC = () => {
  const { selectedModel, setModel, models } = useThreadStore();

  return (
    <>
    <ScrollController />
    <ThreadPrimitive.Root
      className="aui-root aui-thread-root @container flex h-full flex-col bg-background"
      style={{
        ["--thread-max-width" as string]: "44rem",
        ["--composer-radius" as string]: "24px",
        ["--composer-padding" as string]: "10px",
      }}
    >
      <div className="flex items-center justify-center m-4 gap-1">
        <ModelSelector
          models={models}
          value={selectedModel}
          onValueChange={setModel}
          size="default"
        />
      </div>

      <ThreadPrimitive.Viewport
        className="aui-thread-viewport relative flex flex-1 flex-col overflow-x-auto overflow-y-scroll scroll-smooth px-4 pt-4"
      >
        <AuiIf condition={(s) => s.thread.isEmpty}>
          <ThreadWelcome />
        </AuiIf>

        <ThreadPrimitive.Messages>
          {() => <ThreadMessage />}
        </ThreadPrimitive.Messages>

        {/* Throbber — only shown while the backend is processing */}
        <GeneratingMessage />

        <ThreadPrimitive.ViewportFooter className="aui-thread-viewport-footer sticky bottom-0 mx-auto mt-auto flex w-full max-w-(--thread-max-width) flex-col gap-4 overflow-visible rounded-t-(--composer-radius) bg-background pb-4 md:pb-6">
          <ThreadScrollToBottom />
          <Composer />
          <p className="text-center text-[10px] text-foreground/80 px-4 leading-relaxed">
            AIは間違いを犯す可能性があるため、慎重に使用してください。
          </p>
        </ThreadPrimitive.ViewportFooter>
      </ThreadPrimitive.Viewport>
    </ThreadPrimitive.Root>
    </>
  );
};

const ThreadMessage: FC = () => {
  const role = useAuiState((s) => s.message.role);
  const isEditing = useAuiState((s) => s.message.composer.isEditing);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const isRunningPlaceholder = useAuiState((s: any) => s.message?.status?.type === "running");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const messageId = useAuiState((s: any) => s.message?.id as string ?? "");

  if (isEditing) return <EditComposer />;
  if (role === "user") return <UserMessage />;
  if (isRunningPlaceholder) return null;
  return <AssistantMessage messageId={messageId} />;
};

// ── Generating throbber ────────────────────────────────────────────────────

const GeneratingMessage: FC = () => {
  return (
    <AuiIf condition={(s) => s.thread.isRunning}>
      <div
        className="fade-in slide-in-from-bottom-1 mx-auto w-full max-w-(--thread-max-width) animate-in py-3 duration-150"
        aria-label="AI is generating a response"
        aria-live="polite"
      >
        <div className="flex gap-3 items-start px-2">
          <AssistantAvatar pulse />
          {/* Bouncing dots aligned with message text */}
          <div className="flex items-center gap-1.5 mt-1.5">
            <span className="size-2 rounded-full bg-foreground/35 animate-bounce [animation-delay:0ms]" />
            <span className="size-2 rounded-full bg-foreground/35 animate-bounce [animation-delay:150ms]" />
            <span className="size-2 rounded-full bg-foreground/35 animate-bounce [animation-delay:300ms]" />
          </div>
        </div>
      </div>
    </AuiIf>
  );
};

// ── Scroll to bottom ───────────────────────────────────────────────────────

const ThreadScrollToBottom: FC = () => {
  return (
    <ThreadPrimitive.ScrollToBottom asChild>
      <TooltipIconButton
        tooltip="Scroll to bottom"
        variant="outline"
        className="aui-thread-scroll-to-bottom absolute -top-12 z-10 self-center rounded-full p-4 disabled:invisible dark:border-border dark:bg-background dark:hover:bg-accent"
      >
        <ArrowDownIcon />
      </TooltipIconButton>
    </ThreadPrimitive.ScrollToBottom>
  );
};

// ── Welcome screen ─────────────────────────────────────────────────────────

const ThreadWelcome: FC = () => {
  return (
    <div className="aui-thread-welcome-root mx-auto my-auto flex w-full max-w-(--thread-max-width) grow flex-col">
      <div className="aui-thread-welcome-center flex w-full grow flex-col items-center justify-center">
        <div className="aui-thread-welcome-message flex size-full flex-col justify-center px-4">
          <h1 className="aui-thread-welcome-message-inner fade-in slide-in-from-bottom-1 animate-in fill-mode-both font-semibold text-2xl duration-200">
            共立RAGへようこそ
          </h1>
          <br />
          <p className="aui-thread-welcome-message-inner fade-in slide-in-from-bottom-1 animate-in fill-mode-both text-muted-foreground text-xl delay-75 duration-200">
            どのようなご用件でしょうか？
          </p>
        </div>
      </div>
      <ThreadSuggestions />
    </div>
  );
};

const ThreadSuggestions: FC = () => {
  return (
    <div className="aui-thread-welcome-suggestions grid w-full @md:grid-cols-2 gap-2 pb-4">
      <ThreadPrimitive.Suggestions>
        {() => <ThreadSuggestionItem />}
      </ThreadPrimitive.Suggestions>
    </div>
  );
};

const ThreadSuggestionItem: FC = () => {
  return (
    <div className="aui-thread-welcome-suggestion-display fade-in slide-in-from-bottom-2 @md:nth-[n+3]:block nth-[n+3]:hidden animate-in fill-mode-both duration-200">
      <SuggestionPrimitive.Trigger send asChild>
        <Button
          variant="ghost"
          className="aui-thread-welcome-suggestion h-auto w-full @md:flex-col flex-wrap items-start justify-start gap-1 rounded-3xl border bg-background px-4 py-3 text-left text-sm transition-colors hover:bg-muted"
        >
          <SuggestionPrimitive.Title className="aui-thread-welcome-suggestion-text-1 font-medium" />
          <SuggestionPrimitive.Description className="aui-thread-welcome-suggestion-text-2 text-muted-foreground empty:hidden" />
        </Button>
      </SuggestionPrimitive.Trigger>
    </div>
  );
};

// ── Composer ───────────────────────────────────────────────────────────────

const Composer: FC = () => {
  return (
    <ComposerPrimitive.Root className="aui-composer-root relative flex w-full flex-col">
      <ComposerPrimitive.AttachmentDropzone asChild>
        <div
          data-slot="composer-shell"
          className="flex w-full flex-col gap-2 rounded-(--composer-radius) border bg-background p-(--composer-padding) transition-shadow focus-within:border-ring/75 focus-within:ring-2 focus-within:ring-ring/20 data-[dragging=true]:border-ring data-[dragging=true]:border-dashed data-[dragging=true]:bg-accent/50"
        >

          <ComposerPrimitive.Input
            placeholder="何か質問はありますか？..."
            className="aui-composer-input max-h-32 min-h-10 w-full resize-none bg-transparent px-1.75 py-1 text-sm outline-none placeholder:text-muted-foreground/80"
            rows={1}
            autoFocus
            aria-label="Message input"
          />
          <ComposerAction />
        </div>
      </ComposerPrimitive.AttachmentDropzone>
    </ComposerPrimitive.Root>
  );
};

const ComposerAction: FC = () => {
  return (
    <div className="aui-composer-action-wrapper relative flex items-center justify-between">

      <AuiIf condition={(s) => !s.thread.isRunning}>
        <ComposerPrimitive.Send asChild>
          <TooltipIconButton
            tooltip="Send message"
            side="bottom"
            type="button"
            variant="default"
            size="icon"
            className="aui-composer-send size-8 rounded-full"
            aria-label="Send message"
          >
            <ArrowUpIcon className="aui-composer-send-icon size-4" />
          </TooltipIconButton>
        </ComposerPrimitive.Send>
      </AuiIf>
      <AuiIf condition={(s) => s.thread.isRunning}>
        <ComposerPrimitive.Cancel asChild>
          <Button
            type="button"
            variant="default"
            size="icon"
            className="aui-composer-cancel size-8 rounded-full"
            aria-label="Stop generating"
          >
            <SquareIcon className="aui-composer-cancel-icon size-3 fill-current" />
          </Button>
        </ComposerPrimitive.Cancel>
      </AuiIf>
    </div>
  );
};

// ── Error ──────────────────────────────────────────────────────────────────

const MessageError: FC = () => {
  return (
    <MessagePrimitive.Error>
      <ErrorPrimitive.Root className="aui-message-error-root mt-2 rounded-md border border-destructive bg-destructive/10 p-3 text-destructive text-sm dark:bg-destructive/5 dark:text-red-200">
        <ErrorPrimitive.Message className="aui-message-error-message line-clamp-2" />
      </ErrorPrimitive.Root>
    </MessagePrimitive.Error>
  );
};

// ── Assistant message ──────────────────────────────────────────────────────

const AssistantMessage: FC<{ messageId: string }> = ({ messageId }) => {
  const citations = useThreadStore((s) => {
    const thread = s.threads.find((t) => t.id === s.currentThreadId);
    return thread?.messages.find((m) => m.id === messageId)?.citations;
  });

  return (
    <MessagePrimitive.Root
      className="aui-assistant-message-root fade-in slide-in-from-bottom-1 mx-auto w-full max-w-(--thread-max-width) animate-in py-3 duration-150"
      data-role="assistant"
    >
      <div className="flex gap-3 items-start px-2">
        {/* Sparkle avatar — the AI message primitive indicator */}
        <AssistantAvatar />

        {/* Content column */}
        <div className="flex-1 min-w-0">
          <div className="aui-assistant-message-content wrap-break-word text-foreground leading-relaxed">
            <MessagePrimitive.Parts>
              {({ part }) => {
                if (part.type === "text") return <MarkdownText />;
                if (part.type === "tool-call")
                  return part.toolUI ?? <ToolFallback {...part} />;
                return null;
              }}
            </MessagePrimitive.Parts>
            <MessageError />
          </div>

          {citations && citations.length > 0 && (
            <CitationList citations={citations} />
          )}

          <div className="aui-assistant-message-footer mt-1 flex min-h-6 items-center">
            <BranchPicker />
            <AssistantActionBar />
          </div>
        </div>
      </div>
    </MessagePrimitive.Root>
  );
};

// ── Citations ──────────────────────────────────────────────────────────────

const CitationList: FC<{ citations: Citation[] }> = ({ citations }) => {
  return (
    <div className="mt-3 mb-1 space-y-1.5">
      <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
        Citations
      </p>
      <div className="flex flex-wrap gap-2">
        {citations.map((c, i) => (
          <div
            key={i}
            className="flex items-start gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs max-w-[240px] hover:bg-muted/70 transition-colors"
          >
            {/* Index badge */}
            <span className="mt-0.5 shrink-0 flex size-4 items-center justify-center rounded-full bg-primary/15 font-mono text-[10px] font-bold text-primary">
              {i + 1}
            </span>
            <div className="min-w-0">
              {/* Filename with underline accent */}
              <p
                className="font-semibold text-foreground truncate border-b border-foreground/25 pb-0.5 mb-0.5"
                title={c.file_name}
              >
                {c.source_url ? <button onClick={() => void downloadSource(c.source_url!, c.file_name).catch(report)}>{c.file_name}</button> : c.file_name}
              </p>
              {/* Folder path */}
              <p className="text-muted-foreground truncate" title={c.folder}>
                {c.folder}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const AssistantActionBar: FC = () => {
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="aui-assistant-action-bar-root -ml-1 flex gap-1 text-muted-foreground"
    >
      <ActionBarPrimitive.Copy asChild>
        <TooltipIconButton tooltip="Copy">
          <AuiIf condition={(s) => s.message.isCopied}>
            <CheckIcon />
          </AuiIf>
          <AuiIf condition={(s) => !s.message.isCopied}>
            <CopyIcon />
          </AuiIf>
        </TooltipIconButton>
      </ActionBarPrimitive.Copy>
      <ActionBarPrimitive.Reload asChild>
        <TooltipIconButton tooltip="Refresh">
          <RefreshCwIcon />
        </TooltipIconButton>
      </ActionBarPrimitive.Reload>
      <ActionBarMorePrimitive.Root>
        <ActionBarMorePrimitive.Trigger asChild>
          <TooltipIconButton
            tooltip="More"
            className="data-[state=open]:bg-accent"
          >
            <MoreHorizontalIcon />
          </TooltipIconButton>
        </ActionBarMorePrimitive.Trigger>
        <ActionBarMorePrimitive.Content
          side="bottom"
          align="start"
          className="aui-action-bar-more-content z-50 min-w-32 overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md"
        >
          <ActionBarPrimitive.ExportMarkdown asChild>
            <ActionBarMorePrimitive.Item className="aui-action-bar-more-item flex cursor-pointer select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground">
              <DownloadIcon className="size-4" />
              Export as Markdown
            </ActionBarMorePrimitive.Item>
          </ActionBarPrimitive.ExportMarkdown>
        </ActionBarMorePrimitive.Content>
      </ActionBarMorePrimitive.Root>
    </ActionBarPrimitive.Root>
  );
};

// ── User message ───────────────────────────────────────────────────────────

const UserMessage: FC = () => {
  return (
    <MessagePrimitive.Root
      className="aui-user-message-root fade-in slide-in-from-bottom-1 mx-auto grid w-full max-w-(--thread-max-width) animate-in auto-rows-auto grid-cols-[minmax(72px,1fr)_auto] content-start gap-y-2 px-2 py-3 duration-150 [&:where(>*)]:col-start-2"
      data-role="user"
    >
      <UserMessageAttachments />

      <div className="aui-user-message-content-wrapper relative col-start-2 min-w-0">
        <div className="aui-user-message-content wrap-break-word peer rounded-2xl bg-muted px-4 py-2.5 text-foreground empty:hidden">
          <MessagePrimitive.Parts />
        </div>
        <div className="aui-user-action-bar-wrapper absolute top-1/2 left-0 -translate-x-full -translate-y-1/2 pr-2 peer-empty:hidden">
          <UserActionBar />
        </div>
      </div>

      <BranchPicker className="aui-user-branch-picker col-span-full col-start-1 row-start-3 -mr-1 justify-end" />
    </MessagePrimitive.Root>
  );
};

const UserActionBar: FC = () => {
  return (
    <ActionBarPrimitive.Root
      hideWhenRunning
      autohide="not-last"
      className="aui-user-action-bar-root flex flex-col items-end"
    >
      <ActionBarPrimitive.Edit asChild>
        <TooltipIconButton tooltip="Edit" className="aui-user-action-edit p-4">
          <PencilIcon />
        </TooltipIconButton>
      </ActionBarPrimitive.Edit>
    </ActionBarPrimitive.Root>
  );
};

// ── Edit composer ──────────────────────────────────────────────────────────

const EditComposer: FC = () => {
  return (
    <MessagePrimitive.Root className="aui-edit-composer-wrapper mx-auto flex w-full max-w-(--thread-max-width) flex-col px-2 py-3">
      <ComposerPrimitive.Root className="aui-edit-composer-root ml-auto flex w-full max-w-[85%] flex-col rounded-2xl bg-muted">
        <ComposerPrimitive.Input
          className="aui-edit-composer-input min-h-14 w-full resize-none bg-transparent p-4 text-foreground text-sm outline-none"
          autoFocus
        />
        <div className="aui-edit-composer-footer mx-3 mb-3 flex items-center gap-2 self-end">
          <ComposerPrimitive.Cancel asChild>
            <Button variant="ghost" size="sm">
              Cancel
            </Button>
          </ComposerPrimitive.Cancel>
          <ComposerPrimitive.Send asChild>
            <Button size="sm">Update</Button>
          </ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
    </MessagePrimitive.Root>
  );
};

// ── Branch picker ──────────────────────────────────────────────────────────

const BranchPicker: FC<BranchPickerPrimitive.Root.Props> = ({
  className,
  ...rest
}) => {
  return (
    <BranchPickerPrimitive.Root
      hideWhenSingleBranch
      className={cn(
        "aui-branch-picker-root mr-2 -ml-2 inline-flex items-center text-muted-foreground text-xs",
        className,
      )}
      {...rest}
    >
      <BranchPickerPrimitive.Previous asChild>
        <TooltipIconButton tooltip="Previous">
          <ChevronLeftIcon />
        </TooltipIconButton>
      </BranchPickerPrimitive.Previous>
      <span className="aui-branch-picker-state font-medium">
        <BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count />
      </span>
      <BranchPickerPrimitive.Next asChild>
        <TooltipIconButton tooltip="Next">
          <ChevronRightIcon />
        </TooltipIconButton>
      </BranchPickerPrimitive.Next>
    </BranchPickerPrimitive.Root>
  );
};
