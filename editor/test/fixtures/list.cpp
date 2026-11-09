#include <iostream>
#include <vector>
#define SQUARE(x) \
    ((x) * (x))

namespace demo {

template <typename T>
struct Node {
    T value;
    Node* next = nullptr;
};

class List {
public:
    List() : head(nullptr), count(0) {}
    ~List() { clear(); }

    void push(int v)
    {
        Node<int>* n = new Node<int>{v, head};
        head = n;
        ++count;
    }

    int size() const noexcept { return count; }

    void clear() {
        while (head) {
            Node<int>* nx = head->next;
            delete head;
            head = nx;
        }
        count = 0;
    }

private:
    Node<int>* head;
    int count;
};

}  // namespace demo

int main(int argc, char** argv) {
    std::vector<int> nums = {
        1'000, 2,
        3
    };
    demo::List l;
    for (int x : nums)
        l.push(x);
    char c = '}';
    std::cout << "size: "
              << l.size()
              << std::endl;
    auto f = [](int a) {
        return a * 2;
    };
    return f(SQUARE(2)) > 0 ? 0 : 1;
}
