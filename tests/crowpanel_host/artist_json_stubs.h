// Value-only facade for the small ArduinoJson surface used by the production
// credit adapter. It models types and string lengths, not a JSON parser.
#pragma once

#include <initializer_list>
#include <map>
#include <string>
#include <vector>

struct JsonNode {
    enum Kind { Null, String, Number, Boolean, Array, Object } kind = Null;
    std::string string;
    std::vector<JsonNode> array;
    std::map<std::string, JsonNode> object;

    static JsonNode str(const std::string &value) {
        JsonNode node; node.kind = String; node.string = value; return node;
    }
    static JsonNode list(std::initializer_list<JsonNode> values) {
        JsonNode node; node.kind = Array; node.array = values; return node;
    }
    static JsonNode obj(std::initializer_list<std::pair<const std::string, JsonNode>> values) {
        JsonNode node; node.kind = Object; node.object = values; return node;
    }
    static JsonNode number() { JsonNode node; node.kind = Number; return node; }
};

// A const variant exposes only const container views in ArduinoJson7.
struct JsonObjectConst {};

class JsonString {
public:
    explicit JsonString(const std::string *value) : value_(value) {}
    const char *c_str() const { return value_ ? value_->c_str() : nullptr; }
    size_t size() const { return value_ ? value_->size() : 0; }
private:
    const std::string *value_;
};

class JsonVariantConst;

class JsonArrayConst {
public:
    explicit JsonArrayConst(const JsonNode *node = nullptr) : node_(node) {}
    size_t size() const { return values().size(); }
    JsonVariantConst operator[](size_t index) const;
    std::vector<JsonNode>::const_iterator begin() const { return values().begin(); }
    std::vector<JsonNode>::const_iterator end() const { return values().end(); }
private:
    const JsonNode *node_;
    const std::vector<JsonNode> &values() const {
        static const std::vector<JsonNode> empty;
        return node_ && node_->kind == JsonNode::Array ? node_->array : empty;
    }
};

class JsonVariantConst {
public:
    explicit JsonVariantConst(const JsonNode *node = nullptr) : node_(node) {}
    JsonVariantConst(const JsonNode &node) : node_(&node) {}
    bool isNull() const { return !node_ || node_->kind == JsonNode::Null; }
    template<typename T> bool is() const;
    template<typename T> T as() const;
    JsonVariantConst operator[](const char *key) const {
        if (!node_ || node_->kind != JsonNode::Object) return JsonVariantConst();
        const auto found = node_->object.find(key);
        return found == node_->object.end() ? JsonVariantConst() : JsonVariantConst(&found->second);
    }
private:
    const JsonNode *node_;
};

inline JsonVariantConst JsonArrayConst::operator[](size_t index) const {
    return index < values().size() ? JsonVariantConst(&values()[index]) : JsonVariantConst();
}
template<> inline bool JsonVariantConst::is<const char *>() const {
    return node_ && node_->kind == JsonNode::String;
}
template<> inline bool JsonVariantConst::is<JsonArrayConst>() const {
    return node_ && node_->kind == JsonNode::Array;
}
template<> inline bool JsonVariantConst::is<JsonObjectConst>() const {
    return node_ && node_->kind == JsonNode::Object;
}
template<> inline JsonString JsonVariantConst::as<JsonString>() const {
    return JsonString(is<const char *>() ? &node_->string : nullptr);
}
template<> inline JsonArrayConst JsonVariantConst::as<JsonArrayConst>() const {
    return JsonArrayConst(node_);
}
