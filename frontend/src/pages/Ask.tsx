import {
  Alert,
  Box,
  Button,
  Chip,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useState } from "react";

import { useAsk } from "../api/hooks";

const EXAMPLES = [
  "What is the most serious defect in report 1?",
  "Summarize the ventilation problems in the child care center.",
];

export default function Ask() {
  const ask = useAsk();
  const [question, setQuestion] = useState("");

  const submit = (q: string) => {
    const text = q.trim();
    if (text) ask.mutate(text);
  };

  return (
    <Box sx={{ maxWidth: 900 }}>
      <Typography variant="h5" gutterBottom>
        Ask the corpus (semantic)
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        For fuzzy/open-ended questions. Use Analytics for exact counts. You can
        refer to reports by number (e.g. "report 1") — see the IDs in Browse/Analytics.
      </Typography>

      <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: "wrap", gap: 1 }}>
        {EXAMPLES.map((ex) => (
          <Chip key={ex} label={ex} variant="outlined" onClick={() => setQuestion(ex)} />
        ))}
      </Stack>

      <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
        <TextField
          fullWidth
          label="Question"
          placeholder="What is the most serious defect in report 1?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit(question);
          }}
        />
        <Button variant="contained" disabled={ask.isPending} onClick={() => submit(question)}>
          {ask.isPending ? "Retrieving…" : "Ask"}
        </Button>
      </Stack>

      {ask.isError && <Alert severity="error">The query failed. Please try again.</Alert>}

      {ask.data && (
        <Paper sx={{ p: 2 }}>
          {ask.data.scope.length > 0 && (
            <Typography variant="caption" color="text.secondary">
              Scoped to: {ask.data.scope.join(", ")}
            </Typography>
          )}
          <Typography sx={{ whiteSpace: "pre-wrap", my: 1 }}>{ask.data.answer}</Typography>
          <Typography variant="caption" color="text.secondary">
            Sources: {ask.data.sources.join(", ")}
          </Typography>
        </Paper>
      )}
    </Box>
  );
}
