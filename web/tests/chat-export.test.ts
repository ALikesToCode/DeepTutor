import test from "node:test";
import assert from "node:assert/strict";

import { buildChatMarkdown } from "../lib/chat-export";

test("buildChatMarkdown sanitizes attachment inline-code fields", () => {
  const markdown = buildChatMarkdown(
    [
      {
        role: "user",
        content: "hello",
        attachments: [
          {
            type: "file",
            filename: "bad`name.md",
            mime_type: "text/`plain",
          },
        ],
      },
    ],
    {
      title: "Export",
      exportedAt: new Date("2026-01-01T00:00:00.000Z"),
    },
  );

  assert.match(markdown, /`bad'name\.md` \(`text\/'plain`\)/);
  assert.doesNotMatch(markdown, /`bad`name/);
});
