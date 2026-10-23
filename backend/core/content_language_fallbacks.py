"""Offline player-facing fallbacks for the languages offered by Babel Fish."""

SUGGESTIONS = {
    "English": [
        "Look around",
        "Listen carefully",
        "Inspect your belongings",
        "Observe your surroundings",
        "Consider your next move",
    ],
    "German": [
        "Umschauen",
        "Aufmerksam lauschen",
        "Eigene Sachen ansehen",
        "Die Umgebung beobachten",
        "Den nächsten Schritt überlegen",
    ],
    "French": [
        "Regarder autour de soi",
        "Écouter attentivement",
        "Examiner ses affaires",
        "Observer les alentours",
        "Réfléchir à la prochaine action",
    ],
    "Spanish": [
        "Mirar alrededor",
        "Escuchar con atención",
        "Examinar tus pertenencias",
        "Observar el entorno",
        "Pensar en tu próximo paso",
    ],
    "Italian": [
        "Guardarsi intorno",
        "Ascoltare attentamente",
        "Esaminare i propri oggetti",
        "Osservare l'ambiente",
        "Pensare alla prossima mossa",
    ],
    "Japanese": [
        "周囲を見回す",
        "注意深く耳を澄ます",
        "持ち物を確認する",
        "周囲の様子を観察する",
        "次の行動を考える",
    ],
    "Chinese": ["环顾四周", "仔细聆听", "检查随身物品", "观察周围环境", "考虑下一步行动"],
    "Russian": [
        "Осмотреться",
        "Внимательно прислушаться",
        "Осмотреть свои вещи",
        "Понаблюдать за окружением",
        "Обдумать следующий шаг",
    ],
    "Portuguese": [
        "Olhar ao redor",
        "Escutar com atenção",
        "Examinar seus pertences",
        "Observar o ambiente",
        "Pensar no próximo passo",
    ],
}

# Neutral closing lines report the terminal state without inventing story events.
EPILOGUES = {
    "English": (
        "This adventure is complete. Its story remains yours to revisit.",
        "This adventure has ended. Its story remains yours to revisit.",
    ),
    "German": (
        "Dieses Abenteuer ist abgeschlossen. Seine Geschichte bleibt zum Nachlesen erhalten.",
        "Dieses Abenteuer ist zu Ende. Seine Geschichte bleibt zum Nachlesen erhalten.",
    ),
    "French": (
        "Cette aventure est accomplie. Son histoire reste à relire.",
        "Cette aventure est terminée. Son histoire reste à relire.",
    ),
    "Spanish": (
        "Has completado esta aventura. Su historia sigue disponible para releerla.",
        "Esta aventura ha terminado. Su historia sigue disponible para releerla.",
    ),
    "Italian": (
        "Hai completato questa avventura. La sua storia resta da rileggere.",
        "Questa avventura è terminata. La sua storia resta da rileggere.",
    ),
    "Japanese": (
        "この冒険を達成しました。その物語はいつでも読み返せます。",
        "この冒険は終わりました。その物語はいつでも読み返せます。",
    ),
    "Chinese": (
        "你已完成这场冒险。你仍然可以重温它的故事。",
        "这场冒险已经结束。你仍然可以重温它的故事。",
    ),
    "Russian": (
        "Приключение завершено успешно. Его историю можно перечитать.",
        "Приключение окончено. Его историю можно перечитать.",
    ),
    "Portuguese": (
        "Você concluiu esta aventura. Sua história continua disponível para releitura.",
        "Esta aventura chegou ao fim. Sua história continua disponível para releitura.",
    ),
}
