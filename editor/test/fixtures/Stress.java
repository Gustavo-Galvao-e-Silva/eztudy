package ds;

import java.util.*;

public interface Shape {
    double area();

    default String describe() {
        return "area=" + area();
    }
}

abstract class Base<K extends Comparable<K>,
                    V> implements Comparable<Base<K, V>> {
    protected K key;

    public static <T extends Comparable<? super T>> void sort(
            T[] arr,
            Comparator<T> cmp) {
        Arrays.sort(arr, cmp);
    }

    @Override
    public int compareTo(Base<K, V> other) {
        return key == null
            ? -1
            : key.compareTo(other.key);
    }

    int[] grid() {
        return new int[] {
            1, 2,
            3
        };
    }

    Runnable task() {
        return new Runnable() {
            @Override
            public void run() {
                System.out.println("run");
            }
        };
    }

    void loops(List<Integer> xs) {
        for (int i = 0;
             i < xs.size();
             i++) {
            if (xs.get(i) > 0) continue;
            else if (xs.get(i) < 0)
                break;
        }
        Map<String, List<Integer>> m = new HashMap<>();
        m.computeIfAbsent("a", k -> new ArrayList<>())
         .add(1);
        String s = "a"
            + "b";
        boolean ok = xs.isEmpty() &&
            m.isEmpty();
        synchronized (this) {
            key = null;
        }
        static_block: {
            ok = !ok;
        }
    }
}
