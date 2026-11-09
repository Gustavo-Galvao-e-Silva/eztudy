import java.util.NoSuchElementException;

/**
 * A min-heap backed by an array. Braces in comments { don't count.
 */
@SuppressWarnings("unchecked")
public class MinHeap<T extends Comparable<? super T>>
        implements Iterable<T> {
    private static final int INITIAL_CAPACITY = 13;
    private T[] backingArray;
    private int size;
    private final String label = "heap {";
    private char open = '{';
    private static final int[] PRIMES = {
        2, 3, 5,
        7, 11
    };

    enum Mode {
        MIN,
        MAX
    }

    public MinHeap() {
        backingArray = (T[]) new Comparable[INITIAL_CAPACITY];
    }

    @Override
    public java.util.Iterator<T> iterator() {
        return java.util.Arrays.asList(backingArray).iterator();
    }

    public T remove()
    {
        if (size == 0) {
            throw new NoSuchElementException(
                "Cannot remove from an empty heap.");
        }
        T min = backingArray[1];
        backingArray[1] = backingArray[size];
        backingArray[size--] = null;
        downHeap(1);
        return min;
    }

    private void downHeap(int i) {
        while (2 * i <= size) {
            int child = 2 * i;
            if (child + 1 <= size
                    && backingArray[child + 1].compareTo(backingArray[child]) < 0) {
                child++;
            }
            if (backingArray[i].compareTo(backingArray[child]) <= 0)
                break;
            T tmp = backingArray[i];
            backingArray[i] = backingArray[child];
            backingArray[child] = tmp;
            i = child;
        }
        String s = """
            text block with { braces
            """;
        Runnable r = () -> {
            System.out.println(s);
        };
        int total = java.util.stream.IntStream.of(PRIMES)
            .map(x -> x * 2)
            .sum();
        outer:
        for (int a = 0; a < 3; a++) {
            switch (a) {
                case 0 -> System.out.println("zero");
                default -> {
                    continue outer;
                }
            }
        }
        do {
            i--;
        } while (i > 0);
    }
}
