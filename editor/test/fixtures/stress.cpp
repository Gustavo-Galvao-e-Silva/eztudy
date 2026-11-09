#include <map>
#include <string>

using Map = std::map<std::string, int>;

template <typename K,
          typename V>
class Tree
{
public:
    explicit Tree(int cap)
        : cap_(cap),
          root_(nullptr)
    {
    }

    virtual ~Tree() = default;
    virtual int height() const = 0;

    bool contains(const K& key) const
    {
        auto it = index_.find(key);
        return it != index_.end();
    }

protected:
    int cap_;
    void* root_;
    std::map<K, V> index_;
};

enum class Color { Red, Green };

enum Legacy {
    A,
    B
};

static int counter = 0;

int fib(int n)
{
    if (n < 2)
        return n;
    else
        return fib(n - 1)
             + fib(n - 2);
}

struct Point { int x, y; };

int main()
{
    Point p{1,
            2};
    const char* s = R"(raw)";
    do {
        counter++;
    } while (counter < 3);
    switch (p.x) {
        case 1:
            break;
        default:
            break;
    }
    return 0;
}
