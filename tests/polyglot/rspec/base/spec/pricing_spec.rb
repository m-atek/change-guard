require_relative "../lib/shop/pricing"

RSpec.describe Shop::Pricing do
  it "multiplies the unit price by the quantity" do
    expect(described_class.total(250, 4)).to eq(1000)
  end
end
