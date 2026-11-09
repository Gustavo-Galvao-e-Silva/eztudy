use std::collections::HashMap;

pub struct Cache<'a> {
    map: HashMap<&'a str, i32>,
}

impl<'a> Cache<'a> {
    pub fn get(&self, key: &'a str) -> Option<i32> {
        let brace = '{';
        let raw = r#"a "quoted" { brace"#;
        match self.map.get(key) {
            Some(v) => Some(*v),
            None => None,
        }
    }

    fn double(x: i32) -> i32 {
        x * 2
    }
}
