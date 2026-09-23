// Minimal JSON value, parser and writer for vst3host. No dependencies: the host
// must stay a tiny, auditable process that loads untrusted plugins (SPEC §15).
#pragma once
#include <cmath>
#include <cstdint>
#include <map>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

namespace abjson {

struct Value;
using Object = std::map<std::string, Value>;
using Array = std::vector<Value>;

struct Value {
    enum Type { Null, Bool, Number, String, Arr, Obj } type = Null;
    bool b = false;
    double n = 0.0;
    std::string s;
    std::shared_ptr<Array> a;
    std::shared_ptr<Object> o;

    Value() = default;
    Value(std::nullptr_t) {}
    Value(bool v) : type(Bool), b(v) {}
    Value(int v) : type(Number), n(v) {}
    Value(int64_t v) : type(Number), n((double) v) {}
    Value(uint32_t v) : type(Number), n(v) {}
    Value(double v) : type(Number), n(v) {}
    Value(const char* v) : type(String), s(v) {}
    Value(const std::string& v) : type(String), s(v) {}
    Value(const Array& v) : type(Arr), a(std::make_shared<Array>(v)) {}
    Value(const Object& v) : type(Obj), o(std::make_shared<Object>(v)) {}

    static Value array() { Value v; v.type = Arr; v.a = std::make_shared<Array>(); return v; }
    static Value object() { Value v; v.type = Obj; v.o = std::make_shared<Object>(); return v; }

    Value& operator[](const std::string& k) { if (type != Obj) { type = Obj; o = std::make_shared<Object>(); } return (*o)[k]; }
    void push(const Value& v) { if (type != Arr) { type = Arr; a = std::make_shared<Array>(); } a->push_back(v); }

    const Value* get(const std::string& k) const { if (type != Obj) return nullptr; auto it = o->find(k); return it == o->end() ? nullptr : &it->second; }
    std::string str(const std::string& k, const std::string& def = "") const { auto v = get(k); return v && v->type == String ? v->s : def; }
    double num(const std::string& k, double def = 0.0) const { auto v = get(k); return v && v->type == Number ? v->n : def; }
    bool boolean(const std::string& k, bool def = false) const { auto v = get(k); return v && v->type == Bool ? v->b : def; }
    bool has(const std::string& k) const { return get(k) != nullptr; }
};

inline void writeString(std::ostream& os, const std::string& s) {
    os << '"';
    for (unsigned char c : s) {
        switch (c) {
            case '"': os << "\\\""; break;
            case '\\': os << "\\\\"; break;
            case '\n': os << "\\n"; break;
            case '\r': os << "\\r"; break;
            case '\t': os << "\\t"; break;
            default:
                if (c < 0x20) { char buf[8]; snprintf(buf, sizeof buf, "\\u%04x", c); os << buf; }
                else os << (char) c;
        }
    }
    os << '"';
}

inline void write(std::ostream& os, const Value& v) {
    switch (v.type) {
        case Value::Null: os << "null"; break;
        case Value::Bool: os << (v.b ? "true" : "false"); break;
        case Value::Number:
            if (std::isfinite(v.n)) { if (v.n == std::floor(v.n) && std::fabs(v.n) < 1e15) os << (long long) v.n; else { char buf[40]; snprintf(buf, sizeof buf, "%.9g", v.n); os << buf; } }
            else os << "null";
            break;
        case Value::String: writeString(os, v.s); break;
        case Value::Arr: { os << '['; bool first = true; for (auto& e : *v.a) { if (!first) os << ','; first = false; write(os, e); } os << ']'; break; }
        case Value::Obj: { os << '{'; bool first = true; for (auto& kv : *v.o) { if (!first) os << ','; first = false; writeString(os, kv.first); os << ':'; write(os, kv.second); } os << '}'; break; }
    }
}

inline std::string dump(const Value& v) { std::ostringstream os; write(os, v); return os.str(); }

class Parser {
public:
    explicit Parser(const std::string& text) : t(text) {}
    bool parse(Value& out, std::string& err) {
        try { skip(); out = value(); skip(); if (i != t.size()) throw std::runtime_error("trailing characters"); return true; }
        catch (const std::exception& e) { err = e.what(); return false; }
    }
private:
    const std::string& t; size_t i = 0;
    void skip() { while (i < t.size() && (t[i] == ' ' || t[i] == '\n' || t[i] == '\r' || t[i] == '\t')) i++; }
    char peek() { if (i >= t.size()) throw std::runtime_error("unexpected end"); return t[i]; }
    void expect(const char* lit) { for (const char* p = lit; *p; ++p) { if (i >= t.size() || t[i] != *p) throw std::runtime_error(std::string("expected ") + lit); i++; } }
    Value value() {
        skip(); char c = peek();
        if (c == '{') { Value v = Value::object(); i++; skip(); if (peek() == '}') { i++; return v; }
            for (;;) { skip(); std::string k = string(); skip(); expect(":"); (*v.o)[k] = value(); skip(); if (peek() == ',') { i++; continue; } expect("}"); return v; } }
        if (c == '[') { Value v = Value::array(); i++; skip(); if (peek() == ']') { i++; return v; }
            for (;;) { v.a->push_back(value()); skip(); if (peek() == ',') { i++; continue; } expect("]"); return v; } }
        if (c == '"') return Value(string());
        if (c == 't') { expect("true"); return Value(true); }
        if (c == 'f') { expect("false"); return Value(false); }
        if (c == 'n') { expect("null"); return Value(); }
        return number();
    }
    std::string string() {
        expect("\""); std::string s;
        for (;;) { char c = peek(); i++;
            if (c == '"') return s;
            if (c == '\\') { char e = peek(); i++;
                switch (e) { case '"': s += '"'; break; case '\\': s += '\\'; break; case '/': s += '/'; break; case 'b': s += '\b'; break;
                    case 'f': s += '\f'; break; case 'n': s += '\n'; break; case 'r': s += '\r'; break; case 't': s += '\t'; break;
                    case 'u': { if (i + 4 > t.size()) throw std::runtime_error("bad \\u"); unsigned cp = std::stoul(t.substr(i, 4), nullptr, 16); i += 4;
                        if (cp < 0x80) s += (char) cp; else if (cp < 0x800) { s += (char) (0xC0 | (cp >> 6)); s += (char) (0x80 | (cp & 0x3F)); }
                        else { s += (char) (0xE0 | (cp >> 12)); s += (char) (0x80 | ((cp >> 6) & 0x3F)); s += (char) (0x80 | (cp & 0x3F)); } break; }
                    default: throw std::runtime_error("bad escape"); } }
            else s += c; }
    }
    Value number() {
        size_t start = i; if (peek() == '-') i++;
        while (i < t.size() && (isdigit((unsigned char) t[i]) || t[i] == '.' || t[i] == 'e' || t[i] == 'E' || t[i] == '+' || t[i] == '-')) i++;
        if (start == i) throw std::runtime_error("bad token");
        return Value(std::stod(t.substr(start, i - start)));
    }
};

inline bool parse(const std::string& text, Value& out, std::string& err) { return Parser(text).parse(out, err); }

inline std::string base64(const unsigned char* data, size_t len) {
    static const char* tbl = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out; out.reserve((len + 2) / 3 * 4);
    for (size_t i = 0; i < len; i += 3) {
        unsigned v = data[i] << 16 | (i + 1 < len ? data[i + 1] << 8 : 0) | (i + 2 < len ? data[i + 2] : 0);
        out += tbl[(v >> 18) & 63]; out += tbl[(v >> 12) & 63];
        out += i + 1 < len ? tbl[(v >> 6) & 63] : '='; out += i + 2 < len ? tbl[v & 63] : '=';
    }
    return out;
}

inline std::vector<unsigned char> unbase64(const std::string& s) {
    std::vector<unsigned char> out; int val = 0, bits = -8;
    for (unsigned char c : s) {
        int d = c >= 'A' && c <= 'Z' ? c - 'A' : c >= 'a' && c <= 'z' ? c - 'a' + 26 : c >= '0' && c <= '9' ? c - '0' + 52 : c == '+' ? 62 : c == '/' ? 63 : -1;
        if (d < 0) continue;
        val = (val << 6) | d; bits += 6;
        if (bits >= 0) { out.push_back((unsigned char) ((val >> bits) & 0xFF)); bits -= 8; }
    }
    return out;
}

} // namespace abjson
