#pragma once

#include <cstdint>
#include <ctime>
#include <map>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

class Player;
class PlayerbotAI;

// A whitelisted command extracted from a sidecar reply. Parsed on the async
// response thread, executed on the world thread (never call Execute off it).
// uint32_t keeps this header self-contained (no cmangos includes, matching
// PlayerbotLLMInterface.h); it is the same underlying type as cmangos uint32.
struct PendingDirective
{
    std::string verb;
    std::map<std::string, std::string> args;
    uint32_t requesterGuid = 0;
    time_t enqueuedAt = 0;
};

class LLMDirectiveHandler
{
public:
    // Thread-safe, no game-object access: pulls {"directive":{...}} out of the
    // raw sidecar response body. Returns false when absent or malformed.
    static bool ExtractDirective(const std::string& rawResponse, PendingDirective& directive);

    static void Enqueue(uint32_t botGuid, const PendingDirective& directive);
    static std::vector<PendingDirective> Drain(uint32_t botGuid);

    // World thread only. Re-validates requester/whitelist/freshness, then routes
    // to HandleCommand / ChangeStrategy / Group::ChangeLeader.
    static void Execute(Player* bot, PlayerbotAI* ai, const PendingDirective& directive);

private:
    static std::string ExtractJsonStringValue(const std::string& object, const std::string& key);

    static std::mutex queueMutex;
    static std::unordered_map<uint32_t, std::vector<PendingDirective>> queues;
};
