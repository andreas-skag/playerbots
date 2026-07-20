#include "playerbot/LLMDirectiveHandler.h"

#include "playerbot/playerbot.h"
#include "playerbot/PlayerbotAIConfig.h"

#include <algorithm>

std::mutex LLMDirectiveHandler::queueMutex;
std::unordered_map<uint32_t, std::vector<PendingDirective>> LLMDirectiveHandler::queues;

namespace
{
    const time_t DIRECTIVE_MAX_AGE_SECONDS = 10;

    bool IsValidMark(const std::string& mark)
    {
        static const std::vector<std::string> marks =
            { "star", "circle", "diamond", "triangle", "moon", "square", "cross", "skull" };
        return std::find(marks.begin(), marks.end(), mark) != marks.end();
    }
}

std::string LLMDirectiveHandler::ExtractJsonStringValue(const std::string& object, const std::string& key)
{
    size_t keyPos = object.find("\"" + key + "\"");
    if (keyPos == std::string::npos)
        return "";
    size_t colon = object.find(':', keyPos);
    if (colon == std::string::npos)
        return "";
    size_t openQuote = object.find('"', colon);
    if (openQuote == std::string::npos)
        return "";
    size_t closeQuote = object.find('"', openQuote + 1);
    if (closeQuote == std::string::npos)
        return "";
    return object.substr(openQuote + 1, closeQuote - openQuote - 1);
}

bool LLMDirectiveHandler::ExtractDirective(const std::string& rawResponse, PendingDirective& directive)
{
    size_t keyPos = rawResponse.find("\"directive\"");
    if (keyPos == std::string::npos)
        return false;
    size_t start = rawResponse.find('{', keyPos);
    if (start == std::string::npos)
        return false;
    int depth = 0;
    size_t end = start;
    for (; end < rawResponse.size(); end++)
    {
        if (rawResponse[end] == '{') depth++;
        if (rawResponse[end] == '}' && --depth == 0) break;
    }
    if (end >= rawResponse.size())
        return false;

    std::string object = rawResponse.substr(start, end - start + 1);
    directive.verb = ExtractJsonStringValue(object, "verb");
    if (directive.verb.empty())
        return false;

    size_t argsPos = object.find("\"args\"");
    if (argsPos != std::string::npos)
    {
        size_t argsStart = object.find('{', argsPos);
        size_t argsEnd = argsStart == std::string::npos ? std::string::npos : object.find('}', argsStart);
        if (argsStart != std::string::npos && argsEnd != std::string::npos)
        {
            std::string argsObject = object.substr(argsStart, argsEnd - argsStart + 1);
            std::string mark = ExtractJsonStringValue(argsObject, "mark");
            if (!mark.empty())
                directive.args["mark"] = mark;
        }
    }
    return true;
}

void LLMDirectiveHandler::Enqueue(uint32_t botGuid, const PendingDirective& directive)
{
    std::lock_guard<std::mutex> lock(queueMutex);
    queues[botGuid].push_back(directive);
}

std::vector<PendingDirective> LLMDirectiveHandler::Drain(uint32_t botGuid)
{
    std::lock_guard<std::mutex> lock(queueMutex);
    auto it = queues.find(botGuid);
    if (it == queues.end())
        return {};
    std::vector<PendingDirective> result = std::move(it->second);
    queues.erase(it);
    return result;
}

void LLMDirectiveHandler::Execute(Player* bot, PlayerbotAI* ai, const PendingDirective& directive)
{
    if (time(nullptr) - directive.enqueuedAt > DIRECTIVE_MAX_AGE_SECONDS)
        return;

    Player* requester = sObjectAccessor.FindPlayer(ObjectGuid(HIGHGUID_PLAYER, directive.requesterGuid));
    if (!requester || !requester->IsInWorld())
        return;

    Group* group = bot->GetGroup();
    bool sameGroup = group && requester->GetGroup() == group;
    bool trusted = sPlayerbotAIConfig.llmCommandTrustedGuids.find(directive.requesterGuid)
        != sPlayerbotAIConfig.llmCommandTrustedGuids.end();
    if (!sameGroup && !trusted)
        return;

    const std::string& verb = directive.verb;
    if (verb == "role_tank")
        ai->HandleCommand(CHAT_MSG_WHISPER, "co +tank,-dps", *requester);
    else if (verb == "role_heal")
        ai->HandleCommand(CHAT_MSG_WHISPER, "co +heal,-dps", *requester);
    else if (verb == "role_dps")
        ai->HandleCommand(CHAT_MSG_WHISPER, "co +dps,-tank,-heal", *requester);
    else if (verb == "follow")
    {
        if (group && group->IsLeader(bot->GetObjectGuid()) && sameGroup)
            group->ChangeLeader(requester->GetObjectGuid());
        ai->HandleCommand(CHAT_MSG_WHISPER, "follow", *requester);
    }
    else if (verb == "stay")
        ai->HandleCommand(CHAT_MSG_WHISPER, "stay", *requester);
    else if (verb == "guard")
        ai->HandleCommand(CHAT_MSG_WHISPER, "guard", *requester);
    else if (verb == "flee")
        ai->HandleCommand(CHAT_MSG_WHISPER, "flee", *requester);
    else if (verb == "attack")
    {
        auto markIt = directive.args.find("mark");
        if (markIt != directive.args.end() && IsValidMark(markIt->second))
        {
            ai->HandleCommand(CHAT_MSG_WHISPER, "rti " + markIt->second, *requester);
            ai->HandleCommand(CHAT_MSG_WHISPER, "attack rti target", *requester);
        }
        else
            ai->HandleCommand(CHAT_MSG_WHISPER, "attack my target", *requester);
    }
    else if (verb == "lead")
    {
        if (group && sameGroup && !group->IsLeader(bot->GetObjectGuid()))
            group->ChangeLeader(bot->GetObjectGuid());
        // Stop shadowing the master and let the travel logic walk the dungeon.
        ai->ChangeStrategy("-follow,+travel", BotState::BOT_STATE_NON_COMBAT);
    }
    else if (verb == "loot")
        ai->HandleCommand(CHAT_MSG_WHISPER, "loot", *requester);
    else if (verb == "release")
        ai->HandleCommand(CHAT_MSG_WHISPER, "release", *requester);
    else if (verb == "come")
        ai->HandleCommand(CHAT_MSG_WHISPER, "summon", *requester);
    else if (verb == "give_leader")
        ai->HandleCommand(CHAT_MSG_WHISPER, "give leader", *requester);
    else if (verb == "reset")
        ai->HandleCommand(CHAT_MSG_WHISPER, "reset ai soft", *requester);
    else
        sLog.outBasic("LLMDirectiveHandler: ignoring unknown verb '%s' for bot %s",
            verb.c_str(), bot->GetName());
}
