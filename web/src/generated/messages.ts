/* eslint-disable */
/**
 * Generated from the server's AsyncAPI schema (http://localhost:8010/asyncapi.json).
 * Do not edit by hand — run `npm run generate` instead.
 */

export type AgentMessage =
  | AgentErrorMessage
  | ApprovalRequestMessage
  | ChatMessage
  | HistoryMessage
  | NotificationMessage
  | StreamEndMessage
  | StreamStartMessage
  | SuggestionsMessage
  | TasksUpdatedMessage
  | TextDeltaMessage
  | ToolCallMessage
  | ToolDecisionMessage
  | ToolResultMessage
  | UserMessage;
export type Action = "agent_error";
export type Detail = string;
export type Action1 = "approval_request";
export type ToolCallId = string;
export type ToolName = string;
export type JsonValue = unknown;
export type Calls = ToolCallPayload[];
export type Action2 = "chat";
export type Text = string;
export type Action3 = "history";
export type ConversationId = string;
export type Kind = "text";
export type Role = "user" | "assistant";
export type Content = string;
export type Kind1 = "tool";
export type ToolCallId1 = string;
export type ToolName1 = string;
export type Status = "done" | "denied" | "awaiting";
export type Items = (TextTranscriptItem | ToolTranscriptItem)[];
export type Action4 = "notification";
export type Title = string;
export type Body = string;
export type Action5 = "stream_end";
export type Text1 = string;
export type InputTokens = number;
export type OutputTokens = number;
export type Action6 = "stream_start";
export type ConversationId1 = string;
export type Action7 = "suggestions";
export type FollowUps = string[];
export type Action8 = "tasks_updated";
export type Id = number;
export type Title1 = string;
export type Done = boolean;
export type Tasks = TaskItem[];
export type Action9 = "text_delta";
export type Delta = string;
export type Action10 = "tool_call";
export type Action11 = "tool_decision";
export type ToolCallId2 = string;
export type Approved = boolean;
export type OverrideArgs = {
  [k: string]: JsonValue;
} | null;
export type Reason = string | null;
export type Decisions = ToolDecision[];
export type Action12 = "tool_result";
export type ToolCallId3 = string;
export type Action13 = "user_message";
export type Text2 = string;

/**
 * Something went wrong while running the agent.
 */
export interface AgentErrorMessage {
  action: Action;
  payload: ErrorPayload;
}
export interface ErrorPayload {
  detail: Detail;
}
/**
 * The agent needs user approval before running these tool calls.
 */
export interface ApprovalRequestMessage {
  action: Action1;
  payload: ApprovalRequestPayload;
}
export interface ApprovalRequestPayload {
  calls: Calls;
}
export interface ToolCallPayload {
  tool_call_id: ToolCallId;
  tool_name: ToolName;
  args: Args;
}
export interface Args {
  [k: string]: JsonValue;
}
/**
 * User sends a prompt to the agent.
 */
export interface ChatMessage {
  action: Action2;
  payload: ChatPayload;
}
export interface ChatPayload {
  text: Text;
}
/**
 * Replay of the conversation transcript, sent on connect.
 */
export interface HistoryMessage {
  action: Action3;
  payload: HistoryPayload;
}
export interface HistoryPayload {
  conversation_id: ConversationId;
  items: Items;
}
export interface TextTranscriptItem {
  kind: Kind;
  role: Role;
  content: Content;
}
export interface ToolTranscriptItem {
  kind: Kind1;
  tool_call_id: ToolCallId1;
  tool_name: ToolName1;
  args: Args1;
  status: Status;
  result?: unknown;
}
export interface Args1 {
  [k: string]: JsonValue;
}
/**
 * An out-of-band notification pushed to the conversation, e.g. from an HTTP endpoint.
 */
export interface NotificationMessage {
  action: Action4;
  payload: NotificationPayload;
}
export interface NotificationPayload {
  title: Title;
  body: Body;
}
/**
 * The agent run finished with a final text response.
 */
export interface StreamEndMessage {
  action: Action5;
  payload: StreamEndPayload;
}
export interface StreamEndPayload {
  text: Text1;
  usage: UsageInfo;
}
export interface UsageInfo {
  input_tokens: InputTokens;
  output_tokens: OutputTokens;
}
/**
 * The agent started processing a run.
 */
export interface StreamStartMessage {
  action: Action6;
  payload: StreamStartPayload;
}
export interface StreamStartPayload {
  conversation_id: ConversationId1;
}
/**
 * Suggested next prompts, generated after a completed run.
 */
export interface SuggestionsMessage {
  action: Action7;
  payload: SuggestionsPayload;
}
export interface SuggestionsPayload {
  follow_ups: FollowUps;
}
/**
 * The current state of the task list.
 */
export interface TasksUpdatedMessage {
  action: Action8;
  payload: TasksUpdatedPayload;
}
export interface TasksUpdatedPayload {
  tasks: Tasks;
}
export interface TaskItem {
  id: Id;
  title: Title1;
  done: Done;
}
/**
 * A chunk of the agent's streaming text response.
 */
export interface TextDeltaMessage {
  action: Action9;
  payload: TextDeltaPayload;
}
export interface TextDeltaPayload {
  delta: Delta;
}
/**
 * The agent is calling a tool.
 */
export interface ToolCallMessage {
  action: Action10;
  payload: ToolCallPayload;
}
/**
 * User approves or denies pending tool calls.
 */
export interface ToolDecisionMessage {
  action: Action11;
  payload: ToolDecisionPayload;
}
export interface ToolDecisionPayload {
  decisions: Decisions;
}
export interface ToolDecision {
  tool_call_id: ToolCallId2;
  approved: Approved;
  override_args?: OverrideArgs;
  reason?: Reason;
}
/**
 * A tool call finished and returned a result.
 */
export interface ToolResultMessage {
  action: Action12;
  payload: ToolResultPayload;
}
export interface ToolResultPayload {
  tool_call_id: ToolCallId3;
  content: JsonValue;
}
/**
 * Echo of the user's prompt, broadcast so every connected tab shows it.
 */
export interface UserMessage {
  action: Action13;
  payload: UserMessagePayload;
}
export interface UserMessagePayload {
  text: Text2;
}

export type ClientMessage = ChatMessage | ToolDecisionMessage;
export type ServerMessage = AgentErrorMessage | ApprovalRequestMessage | HistoryMessage | NotificationMessage | StreamEndMessage | StreamStartMessage | SuggestionsMessage | TasksUpdatedMessage | TextDeltaMessage | ToolCallMessage | ToolResultMessage | UserMessage;
export type ServerAction = ServerMessage["action"];
