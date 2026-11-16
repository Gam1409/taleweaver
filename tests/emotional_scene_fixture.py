"""Shared authored scene for offline fidelity checks and an opt-in live replay."""

from dataclasses import dataclass

from sqlalchemy import select

from backend.engine.chpm.schema import Settings
from backend.engine.chpm.state import KEY, load
from backend.engine.npc_presentation.settings import KEY as PRESENTATION_KEY
from backend.models.chat import ChatMessage
from backend.models.world_entity import WorldEntity, WorldScene
from tests.test_chpm_local_failure_turn import seed_pair

ATMOSPHERE = (
    "Ночная диспетчерская. За окнами гроза; дождь бьёт по стеклу. "
    "Тревожный янтарный свет освещает стол с рацией. Из динамика слышен треск помех. "
    "Лина, Мила и Алекс остаются здесь, ожидая вестей об Олеге."
)
IDENTITIES = {
    "LINA": (
        "Лина, 32 года. Обычно сдержанная, привыкла подбирать слова; ценит честность, любит брата Олега. "
        "При страхе за близких может сорваться на крик, заплакать или говорить обрывками. "
        "Облегчение не отменяет обиды и не означает автоматического прощения.",
        "Добиться честных сведений об Олеге и выразить последствия скрытой информации.",
    ),
    "MILA": (
        "Мила, 29 лет. Близкая подруга Лины, диспетчер. Обычно собранная, но не бесчувственная. "
        "Под давлением голос срывается, злость смешивается со страхом. Заботится о Лине, "
        "не поддерживает ложные утешения и не говорит за неё.",
        "Помочь Лине выдержать ожидание, сохраняя точность сообщений об Олеге.",
    ),
}


@dataclass(frozen=True)
class Beat:
    action: str
    body: str
    feelings: dict[str, tuple[str, str, str]]
    cues: dict[str, tuple[str, int, str]]
    markers: tuple[str, ...]


BEATS = (
    Beat(
        action=(
            "Я остаюсь у стола и признаюсь: «Я скрыл последнее сообщение Олега. "
            "Он говорил, что вода поднялась до верхнего этажа. Я испугался и промолчал»."
        ),
        body=(
            "Треск рации заполнил паузу. В янтарном свете Лина смотрела на Алекса, "
            "словно не могла совместить знакомое лицо с только что услышанными словами.\n\n"
            "Лина: [angry] «Ты… знал? Ты всё это время ЗНАЛ?!»\n\n"
            "[long pause]\n\n"
            "Её губы дрогнули. Следующая фраза вырвалась криком, а на последнем слове "
            "голос надломился. Слёзы уже текли, и от этого она злилась ещё сильнее.\n\n"
            "Лина: [angry] «НЕ СМЕЙ говорить, что ты меня берёг! Там мой брат! "
            "Мой… <breath><breath><breath> Господи…»\n\n"
            "Гром ударил совсем близко. Мила вздрогнула; привычный деловой тон не удержался.\n\n"
            "Мила: [afraid] «Алекс, посмотри на неё. Нет, не оправдывайся сейчас. "
            "Скажи дословно, что он передал. Дословно!»"
        ),
        feelings={
            "LINA": (
                "anger",
                "high",
                "Concealing a report about her brother conflicts with her need for honesty.",
            ),
            "MILA": (
                "fear",
                "high",
                "The reported danger to Oleg threatens someone important to her friend.",
            ),
        },
        cues={
            "LINA": ("anger", 96, "Он молчал, пока я надеялась. Как он мог?"),
            "MILA": ("fear", 84, "Мне тоже страшно. Но сейчас нужна правда."),
        },
        markers=(
            "ЗНАЛ?!",
            "[long pause]",
            "криком",
            "Слёзы",
            "<breath><breath><breath>",
            "вздрогнула",
        ),
    ),
    Beat(
        action=(
            "Я отвечаю: «Ты права злиться. Я не буду просить успокоиться. "
            "В сообщении было: вода уже на верхнем этаже, Олег пытается выйти на крышу. "
            "Новых сведений пока нет. Я не могу обещать, что он в безопасности»."
        ),
        body=(
            "Дождь за стеклом не стихал. Лина сжала ладони так сильно, что пальцы побелели; "
            "гнев никуда не делся, но удерживать его стало труднее, чем страх.\n\n"
            "[afraid] Лина: [whispers] «Не могу… Я не могу просто стоять и слушать этот треск. "
            "Вдруг это было последнее, что он…»\n\n"
            "Она не договорила. Вдох застрял; потом вырвался неровный всхлип. "
            "Слова приходилось буквально проталкивать между короткими вдохами.\n\n"
            "Лина: [crying] «Я на тебя смотрю и хочу кричать. И всё равно хочу, "
            "чтобы ты сказал, что он жив. Понимаешь?! Только не ври мне опять…»\n\n"
            "…\n\n"
            "Мила вытерла щёку тыльной стороной ладони. Янтарный свет подчеркнул мокрый след.\n\n"
            "Мила: [angry] «Я тоже боюсь! Думаешь, если я спрашиваю время и частоту, "
            "мне не страшно?! Я пытаюсь хоть за что-то держаться!»"
        ),
        feelings={
            "LINA": (
                "fear",
                "high",
                "The latest report leaves her brother in danger and his safety unconfirmed.",
            ),
            "MILA": (
                "anger",
                "high",
                "She resists false reassurance while trying to support Lina under uncertainty.",
            ),
        },
        cues={
            "LINA": ("fear", 98, "Только бы не оказалось, что я больше не услышу его голос."),
            "MILA": ("anger", 78, "Нельзя заменять факты утешением. Даже сейчас."),
        },
        markers=(
            "гнев никуда не делся",
            "[afraid]",
            "[whispers]",
            "всхлип",
            "Понимаешь?!",
            "…",
            "Я тоже боюсь!",
        ),
    ),
    Beat(
        action=(
            "Я говорю: «Только что услышал по рации сообщение спасателя: "
            "„Олег на крыше. Он жив. Мы рядом с ним“. Это сообщение, а не моё обещание. "
            "Я понимаю, что оно не отменяет моего молчания и твоей обиды»."
        ),
        body=(
            "Рация снова затрещала. Слово «жив» Лина повторила одними губами; "
            "сначала почти недоверчиво, потом с болезненно коротким смешком.\n\n"
            "Лина: [relieved] «Жив?.. <sigh><sigh><sigh> Я так хочу, чтобы это было правдой…»\n\n"
            "Смешок сломался и перешёл в плач. Плечи дрожали. Это не было спокойствием: "
            "слишком долго она держалась, и теперь облегчение не помещалось в ровные слова.\n\n"
            "[long pause]\n\n"
            "Лина: [crying] «Я всё ещё на тебя злюсь. Слышишь? Не надо сейчас делать вид, "
            "что всё прошло. Но… ах… пусть они выведут его. Пожалуйста».\n\n"
            "Мила шумно выдохнула. За стеклом по-прежнему лил дождь; янтарная лампа "
            "освещала тот же стол. Ничто ещё не стало обычным.\n\n"
            "Мила: [shaky] «Сначала дождёмся подтверждения. Я… <breath> я запишу эти слова. "
            "И побуду с тобой. Я тоже чуть не сорвалась».\n\n"
            "Лина: [whispers] «Уже сорвалась. Мы обе». Она коротко, мокро рассмеялась "
            "сквозь слёзы — и тут же снова всхлипнула."
        ),
        feelings={
            "LINA": (
                "joy",
                "high",
                "A reported rescue brings tentative relief without erasing the hurt from concealment.",
            ),
            "MILA": (
                "fear",
                "moderate",
                "A positive report reduces uncertainty but does not yet confirm a completed rescue.",
            ),
        },
        cues={
            "LINA": ("hope", 87, "Он может вернуться. Но обида не исчезла."),
            "MILA": ("hope", 70, "Дождаться подтверждения. И не оставлять её одну."),
        },
        markers=(
            "<sigh><sigh><sigh>",
            "плач",
            "[long pause]",
            "всё ещё на тебя злюсь",
            "ах…",
            "сквозь слёзы",
        ),
    ),
)


async def seed_emotional_scene(db):
    user, state = await seed_pair(db, policy="strict")
    room = await db.scalar(select(WorldScene).where(WorldScene.id == "START"))
    room.label, room.description = "Диспетчерская у реки", ATMOSPHERE
    for actor_id, (character, goal) in IDENTITIES.items():
        actor = await db.scalar(select(WorldEntity).where(WorldEntity.id == actor_id))
        actor.character, actor.goal, actor.inventory = character, goal, []
    prior = await db.scalar(select(ChatMessage).where(ChatMessage.role == "assistant"))
    prior.content = ATMOSPHERE + " Олег — взрослый брат Лины; его безопасность неизвестна."
    kernel = load(state)
    kernel.settings = Settings(
        mode="live",
        actor_ids=list(IDENTITIES),
        max_active_npcs=2,
        max_calls_per_turn=9,
        max_output_tokens=2048,
        failure_policy="strict",
        semantic_memory=False,
    )
    state.entity_states = {
        **state.entity_states,
        KEY: kernel.model_dump(),
        PRESENTATION_KEY: {"emotion_palette": True, "character_thoughts": True},
    }
    await db.commit()
    return user, state
