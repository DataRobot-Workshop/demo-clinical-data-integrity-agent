import { useEffect, useRef, useState } from 'react';
import { MessageCircle, Send } from 'lucide-react';
import { useAskAboutEncounter } from '@/api/integrity/hooks';
import type { ChatTurn } from '@/api/integrity/types';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

const SUGGESTED_QUESTIONS = [
  'What in the note supports the suggested code?',
  'Is there any documentation that would contradict this correction?',
  'How do the on-file code and the suggested code differ?',
  'Why is the confidence at this level?',
];

export function EncounterChatPanel({ encounterId }: { encounterId: string }) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState('');
  const ask = useAskAboutEncounter();
  const scrollRef = useRef<HTMLDivElement>(null);

  // Reset the conversation when the selected encounter changes.
  useEffect(() => {
    setTurns([]);
    setInput('');
  }, [encounterId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [turns, ask.isPending]);

  const send = (question: string) => {
    const q = question.trim();
    if (!q || ask.isPending) return;
    const history = turns;
    setTurns(prev => [...prev, { role: 'user', content: q }]);
    setInput('');
    ask.mutate(
      { encounterId, payload: { question: q, history } },
      {
        onSuccess: r => setTurns(prev => [...prev, { role: 'assistant', content: r.answer }]),
        onError: (err: unknown) =>
          setTurns(prev => [
            ...prev,
            {
              role: 'assistant',
              content: `Sorry — I couldn't answer that. ${(err as Error)?.message ?? ''}`,
            },
          ]),
      }
    );
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <MessageCircle className="h-4 w-4" />
          Ask about this encounter
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          Read-only assistant, grounded in this encounter’s documentation and routed through the
          governed agent deployment (DataRobot moderation guards apply). It can explain and compare,
          but it cannot approve or write anything — that stays with the buttons above.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div
          ref={scrollRef}
          className="max-h-72 space-y-3 overflow-y-auto rounded-md border bg-muted/30 p-3"
        >
          {turns.length === 0 ? (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">Try asking:</p>
              <div className="flex flex-wrap gap-2">
                {SUGGESTED_QUESTIONS.map(q => (
                  <Button
                    key={q}
                    variant="outline"
                    size="sm"
                    className="h-auto whitespace-normal py-1 text-left"
                    onClick={() => send(q)}
                  >
                    {q}
                  </Button>
                ))}
              </div>
            </div>
          ) : (
            turns.map((t, i) => (
              <div
                key={i}
                className={cn('flex', t.role === 'user' ? 'justify-end' : 'justify-start')}
              >
                <div
                  className={cn(
                    'max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm',
                    t.role === 'user'
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-background border'
                  )}
                >
                  {t.content}
                </div>
              </div>
            ))
          )}
          {ask.isPending && (
            <div className="flex justify-start">
              <div className="rounded-lg border bg-background px-3 py-2 text-sm text-muted-foreground">
                Thinking…
              </div>
            </div>
          )}
        </div>

        <form
          className="flex gap-2"
          onSubmit={e => {
            e.preventDefault();
            send(input);
          }}
        >
          <Input
            placeholder="Ask a question about this encounter…"
            value={input}
            onChange={e => setInput(e.target.value)}
            disabled={ask.isPending}
          />
          <Button type="submit" disabled={ask.isPending || !input.trim()}>
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
