import { notifications } from "@mantine/notifications";

import { formatProblem, type Problem } from "../api/problem";

export function showProblem(problem: Problem): void {
  notifications.show({
    color: "red",
    title: problem.title ?? problem.code ?? "Ошибка",
    message: formatProblem(problem),
    autoClose: 8000,
  });
}
