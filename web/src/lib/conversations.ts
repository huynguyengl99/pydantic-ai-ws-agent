// REST client for the conversation list — plain HTTP, outside the AsyncAPI
// pipeline, so the shape is maintained by hand to match server/app/db.py.
export interface Conversation {
  id: string;
  title: string;
  updated_at: string;
}

export async function fetchConversations(
  server: string,
): Promise<Conversation[]> {
  const res = await fetch(`http://${server}/conversations`);
  if (!res.ok) throw new Error(`Failed to list conversations: ${res.status}`);
  return (await res.json()) as Conversation[];
}

export async function deleteConversation(
  server: string,
  id: string,
): Promise<void> {
  const res = await fetch(
    `http://${server}/conversations/${encodeURIComponent(id)}`,
    {
      method: "DELETE",
    },
  );
  if (!res.ok && res.status !== 404) {
    throw new Error(`Failed to delete conversation: ${res.status}`);
  }
}
